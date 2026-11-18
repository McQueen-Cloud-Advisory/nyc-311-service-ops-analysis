// Each invocation uses one source origin for both metadata and data.
// No File.Contents calls, cross-query metadata gates, or credentials.
(tableName as text, columnTypes as list) as table =>
let
    AllowedTables = {"dim_agency", "dim_problem", "dim_borough", "dim_date", "fct_cases", "fct_backlog", "release_metadata"},
    SafeTable = if List.Contains(AllowedTables, tableName) then tableName else error "Unexpected reporting table.",
    SafeRelease = if Text.Length(pReleaseId) > 0 and Text.Length(pReleaseId) <= 63 and Text.Select(Text.Start(pReleaseId, 1), {"a".."z"}) = Text.Start(pReleaseId, 1) and Text.Select(pReleaseId, {"a".."z", "0".."9", "_"}) = pReleaseId then pReleaseId else error "Release ID must start with a lowercase letter and contain at most 63 lowercase letters, digits, or underscores.",
    ValidateProject = (value as text) as text => if Text.Length(value) >= 6 and Text.Length(value) <= 30 and Text.Select(Text.Start(value, 1), {"a".."z"}) = Text.Start(value, 1) and not Text.EndsWith(value, "-") and Text.Select(value, {"a".."z", "0".."9", "-"}) = value then value else error "Set a valid GCP project ID before using BigQuery mode.",
    SafeSourceProject = ValidateProject(pSourceProject),
    SafeBillingProject = ValidateProject(pBillingProject),
    SafeDataset = if Text.Length(pDataset) > 0 and Text.Length(pDataset) <= 1024 and Text.Select(pDataset, {"a".."z", "A".."Z", "0".."9", "_"}) = pDataset then pDataset else error "Invalid BigQuery dataset ID.",
    SafeExportRoot = if Text.Length(pExportRoot) >= 3 and Text.Select(Text.Start(pExportRoot, 1), {"a".."z", "A".."Z"}) = Text.Start(pExportRoot, 1) and Text.Range(pExportRoot, 1, 1) = ":" and List.Contains({"/", "\"}, Text.Range(pExportRoot, 2, 1)) then pExportRoot else error "CSV mode requires an absolute local Windows drive path; network-share paths are not used.",
    MetadataTypes = {{"release_id", type text}, {"snapshot_id", type text}, {"observed_at", type datetimezone}, {"extraction_started_at", type datetimezone}, {"extraction_ended_at", type datetimezone}, {"source_kind", type text}, {"cohort_start", type date}, {"cohort_end", type date}, {"target_version", type text}, {"expected_count", Int64.Type}, {"source_count", Int64.Type}},
    ParseCsv = (content as binary) as table => Table.PromoteHeaders(Csv.Document(Binary.Buffer(content), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]), [PromoteAllScalars=true]),
    // The mode branch is selected before any data-source call. The CSV branch
    // does not inspect or combine a BigQuery connection, and vice versa.
    Raw = if pMode = "CSV" then
        let
            Files = Folder.Contents(SafeExportRoot & "/" & SafeRelease),
            ApprovedFiles = Table.SelectRows(Files, each List.Contains(List.Transform(AllowedTables, each _ & ".csv"), [Name])),
            MetadataBinary = ApprovedFiles{[Name="release_metadata.csv"]}[Content],
            DataBinary = ApprovedFiles{[Name=SafeTable & ".csv"]}[Content]
        in [Metadata=ParseCsv(MetadataBinary), Data=ParseCsv(DataBinary)]
    else if pMode = "BigQuery" then
        let
            Connection = GoogleBigQuery.Database([BillingProject=SafeBillingProject, Implementation="2.0", UseStorageApi=false]),
            Project = Connection{[Name=SafeSourceProject]}[Data],
            // Desktop's ADBC path decoded native TIMESTAMP values incorrectly
            // in the observed release. Format only TIMESTAMP columns as UTC ISO
            // text inside BigQuery, before transport; retain native DATE types.
            // This is a bounded read-only projection, never a numeric correction.
            ReadNative = (modelName as text, types as list) as table =>
                let
                    ApprovedModel = if List.Contains(AllowedTables, modelName) then modelName else error "Unexpected native reporting table.",
                    Projection = List.Transform(types, (columnSpec) =>
                        let
                            Name = columnSpec{0},
                            SafeName = if Text.Length(Name) > 0 and Text.Length(Name) <= 128 and Text.Select(Name, {"a".."z", "0".."9", "_"}) = Name then Name else error "Unexpected native column identifier.",
                            Quoted = "`" & SafeName & "`"
                        in
                            if columnSpec{1} = type datetimezone then "FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E6SZ', " & Quoted & ", 'UTC') AS " & Quoted else Quoted),
                    Sql = "SELECT " & Text.Combine(Projection, ", ") & " FROM `" & SafeSourceProject & "." & SafeDataset & "." & ApprovedModel & "__r_" & SafeRelease & "`"
                in
                    // Keep downstream timezone parsing local so it cannot fold
                    // back into TIMESTAMP transport and reintroduce the defect.
                    Table.StopFolding(Value.NativeQuery(Project, Sql)),
            MetadataTable = ReadNative("release_metadata", MetadataTypes),
            DataTable = ReadNative(SafeTable, columnTypes)
        in [Metadata=MetadataTable, Data=DataTable]
    else error "pMode must be CSV or BigQuery.",
    Convert = (rawTable as table, types as list) as table =>
        let
            RequiredColumns = List.Transform(types, each _{0}),
            Selected = Table.SelectColumns(rawTable, RequiredColumns, MissingField.Error),
            Nulls = Table.TransformColumns(Selected, List.Transform(RequiredColumns, (columnName) => {columnName, (value) => if value is text and value = "" then null else value})),
            Typed = Table.TransformColumnTypes(Nulls, types, "en-US"),
            TimestampColumns = List.Transform(List.Select(types, each _{1} = type datetimezone), each _{0}),
            Utc = Table.TransformColumns(Typed, List.Transform(TimestampColumns, (columnName) => {columnName, each if _ = null then null else DateTimeZone.RemoveZone(DateTimeZone.ToUtc(_)), type nullable datetime})),
            Pinned = if Table.RowCount(Table.SelectRows(Utc, each [release_id] = null or [release_id] <> SafeRelease)) = 0 then Utc else error "Mixed or unexpected release ID. Refresh rejected."
        in Pinned,
    Metadata = Convert(Raw[Metadata], MetadataTypes),
    MetadataRow = if Table.RowCount(Metadata) = 1 then Metadata{0} else error "Release metadata must contain exactly one observation.",
    // Captures describe an already-started creation cohort; observation time is
    // the end of their recorded extraction interval. These bounds fail closed
    // on gross timestamp decoding errors without consulting today's clock.
    CompleteMetadata = if MetadataRow[source_count] = MetadataRow[expected_count]
        and MetadataRow[cohort_start] < MetadataRow[cohort_end]
        and MetadataRow[observed_at] >= DateTime.From(MetadataRow[cohort_start])
        and MetadataRow[extraction_started_at] <= MetadataRow[extraction_ended_at]
        and MetadataRow[observed_at] = MetadataRow[extraction_ended_at]
        then MetadataRow else error "Release capture counts or observation timestamps violate the release contract.",
    // Force the metadata gate in every import without referencing another query.
    Data = if CompleteMetadata[release_id] = SafeRelease then Convert(Raw[Data], columnTypes) else error "Invalid release contract.",
    Result = if SafeTable = "fct_cases" then
        if Table.RowCount(Data) = CompleteMetadata[source_count] and Table.RowCount(Table.SelectRows(Data, each [snapshot_id] <> CompleteMetadata[snapshot_id] or [observed_at] <> CompleteMetadata[observed_at])) = 0 then Data else error "Case details are incomplete or do not match the selected observation."
    else if SafeTable = "fct_backlog" then
        let
            SelectedSnapshot = Table.SelectRows(Data, each [is_release_snapshot] = true and [snapshot_id] = CompleteMetadata[snapshot_id]),
            MatchingObservation = if Table.RowCount(Table.SelectRows(SelectedSnapshot, each [observed_at] <> CompleteMetadata[observed_at])) = 0 then SelectedSnapshot else error "Backlog does not match the selected observation time."
        in MatchingObservation
    else Data
in
    Result
