using System.Text.Json;
using System.Text.Json.Serialization;
using LibProsperoPkg;
using LibProsperoPkg.PKG;

namespace Packizard.PkgBridge;

internal sealed class BuildRequest
{
    [JsonPropertyName("source_folder")]
    public string SourceFolder { get; init; } = "";

    [JsonPropertyName("output_folder")]
    public string OutputFolder { get; init; } = "";

    [JsonPropertyName("content_id")]
    public string ContentId { get; init; } = "";

    [JsonPropertyName("title_id")]
    public string TitleId { get; init; } = "";

    [JsonPropertyName("title")]
    public string Title { get; init; } = "";

    [JsonPropertyName("version")]
    public string Version { get; init; } = "01.00";

    [JsonPropertyName("passcode")]
    public string Passcode { get; init; } = new string('0', 32);

    [JsonPropertyName("mode")]
    public string Mode { get; init; } = nameof(ProsperoPackageMode.Application);

    [JsonPropertyName("output_format")]
    public string OutputFormat { get; init; } = nameof(ProsperoOutputFormat.DebugImage);

    [JsonPropertyName("image_profile")]
    public string ImageProfile { get; init; } = nameof(ProsperoPackageImageProfile.Standard);

    [JsonPropertyName("application_type")]
    public string ApplicationType { get; init; } = nameof(ProsperoApplicationType.NotSpecified);

    [JsonPropertyName("application_drm_type")]
    public string ApplicationDrmType { get; init; } = "standard";

    [JsonPropertyName("generate_param_json_if_missing")]
    public bool GenerateParamJsonIfMissing { get; init; } = true;

    [JsonPropertyName("fake_sign_self_modules")]
    public bool FakeSignSelfModules { get; init; } = true;

    [JsonPropertyName("license_free")]
    public bool LicenseFree { get; init; } = false;

    [JsonPropertyName("verify_after_build")]
    public bool VerifyAfterBuild { get; init; } = true;
}

internal static class Program
{
    private const string EngineVersion = "2.6.0";
    private const string EngineRef = "748eabf1b7d17819528cabf367d8e27109d8fce3";
    private const string PprGuiReferenceVersion = "0.6.8";
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = false,
    };

    private static void Emit(object payload) => Console.WriteLine(JsonSerializer.Serialize(payload, JsonOptions));

    private static string? Option(string[] args, string name)
    {
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (args[i].Equals(name, StringComparison.OrdinalIgnoreCase))
                return args[i + 1];
        }
        return null;
    }

    private static int Main(string[] args)
    {
        try
        {
            if (args.Length == 1 && args[0].Equals("probe", StringComparison.OrdinalIgnoreCase))
            {
                Emit(new
                {
                    type = "probe",
                    engine = "LibProsperoPKG",
                    engineVersion = EngineVersion,
                    engineRef = EngineRef,
                    keysAvailable = ProsperoPackageBuilder.KeysAvailable,
                    pprGuiReferenceVersion = PprGuiReferenceVersion,
                });
                return 0;
            }

            if (args.Length == 3 && args[0].Equals("build", StringComparison.OrdinalIgnoreCase)
                                 && args[1].Equals("--request", StringComparison.OrdinalIgnoreCase))
            {
                return Build(args[2]);
            }

            if (args.Length >= 3 && args[0].Equals("verify", StringComparison.OrdinalIgnoreCase))
            {
                string package = Option(args, "--package")
                    ?? throw new ArgumentException("verify requires --package <path>.");
                return Verify(package, Option(args, "--content-id"));
            }

            if (args.Length >= 7 && args[0].Equals("extract", StringComparison.OrdinalIgnoreCase))
            {
                string package = Option(args, "--package")
                    ?? throw new ArgumentException("extract requires --package <path>.");
                string output = Option(args, "--output")
                    ?? throw new ArgumentException("extract requires --output <directory>.");
                string passcode = Option(args, "--passcode") ?? new string('0', 32);
                return Extract(package, output, passcode);
            }

            Emit(new
            {
                type = "error",
                message = "Usage: Packizard.PkgBridge probe | build --request <request.json> | verify --package <pkg> [--content-id <id>] | extract --package <pkg> --output <dir> --passcode <32-char>"
            });
            return 2;
        }
        catch (Exception ex)
        {
            Emit(new { type = "error", message = ex.Message, details = ex.ToString() });
            return 1;
        }
    }

    private static int Build(string requestPath)
    {
        var json = File.ReadAllText(requestPath);
        var request = JsonSerializer.Deserialize<BuildRequest>(json, JsonOptions)
            ?? throw new InvalidDataException("Invalid build request.");

        if (!Enum.TryParse<ProsperoPackageMode>(request.Mode, true, out var mode))
            throw new ArgumentException($"Unsupported package mode: {request.Mode}");
        if (!Enum.TryParse<ProsperoOutputFormat>(request.OutputFormat, true, out var outputFormat))
            throw new ArgumentException($"Unsupported output format: {request.OutputFormat}");
        if (!Enum.TryParse<ProsperoPackageImageProfile>(request.ImageProfile, true, out var imageProfile))
            throw new ArgumentException($"Unsupported package image profile: {request.ImageProfile}");
        if (!Enum.TryParse<ProsperoApplicationType>(request.ApplicationType, true, out var applicationType))
            throw new ArgumentException($"Unsupported application type: {request.ApplicationType}");

        var options = new ProsperoBuildOptions
        {
            SourceFolder = request.SourceFolder,
            OutputFolder = request.OutputFolder,
            ContentId = request.ContentId,
            TitleId = request.TitleId,
            Title = request.Title,
            Version = string.IsNullOrWhiteSpace(request.Version) ? "01.00" : request.Version.Trim(),
            Passcode = string.IsNullOrWhiteSpace(request.Passcode) ? new string('0', 32) : request.Passcode.Trim(),
            Mode = mode,
            OutputFormat = outputFormat,
            ImageProfile = imageProfile,
            ApplicationType = applicationType,
            GenerateParamJsonIfMissing = request.GenerateParamJsonIfMissing,
            FakeSignSelfModules = request.FakeSignSelfModules,
            LicenseFree = request.LicenseFree,
        };
        if (!string.IsNullOrWhiteSpace(request.ApplicationDrmType))
            options.ApplicationDrmType = request.ApplicationDrmType.Trim();

        Emit(new { type = "log", message = $"Packizard PKG Engine: building {mode} package ({imageProfile} image profile)..." });
        var result = ProsperoPackageBuilder.Build(options, message => Emit(new { type = "log", message }));
        foreach (var warning in result.Warnings)
            Emit(new { type = "warning", message = warning });

        if (request.VerifyAfterBuild)
        {
            Emit(new { type = "log", message = "Verifying finished package structure..." });
            ProsperoAcceptanceReport report = ProsperoPkgValidator.Validate(
                result.OutputPath,
                string.IsNullOrWhiteSpace(request.ContentId) ? null : request.ContentId.Trim());
            foreach (ProsperoAcceptanceCheck check in report.Checks)
            {
                Emit(new
                {
                    type = check.Status == ProsperoCheckStatus.Warning ? "warning" : "log",
                    message = $"Verify [{check.Status}] {check.Name}: {check.Detail}",
                });
            }
            if (!report.Accepted)
                throw new InvalidDataException("The finished package failed structural verification.");
        }

        Emit(new { type = "result", outputPath = result.OutputPath, warnings = result.Warnings });
        return 0;
    }

    private static int Verify(string packagePath, string? expectedContentId)
    {
        Emit(new { type = "log", message = $"Verifying package: {packagePath}" });
        ProsperoAcceptanceReport report = ProsperoPkgValidator.Validate(
            packagePath,
            string.IsNullOrWhiteSpace(expectedContentId) ? null : expectedContentId.Trim());
        foreach (ProsperoAcceptanceCheck check in report.Checks)
        {
            Emit(new
            {
                type = check.Status == ProsperoCheckStatus.Warning ? "warning" : "log",
                message = $"Verify [{check.Status}] {check.Name}: {check.Detail}",
            });
        }
        if (!report.Accepted)
            throw new InvalidDataException("Package verification failed.");
        Emit(new { type = "result", outputPath = packagePath, accepted = true });
        return 0;
    }

    private static int Extract(string packagePath, string outputDirectory, string passcode)
    {
        if (passcode.Length != 32)
            throw new ArgumentException("PKG passcode must contain exactly 32 characters.");
        Emit(new { type = "log", message = $"Extracting package to: {outputDirectory}" });
        ProsperoPackageManifest manifest = ProsperoPackageExtractor.Extract(
            packagePath,
            outputDirectory,
            passcode,
            message => Emit(new { type = "log", message }));
        Emit(new
        {
            type = "result",
            outputPath = manifest.OutputDirectory,
            extractedFileCount = manifest.ExtractedFileCount,
        });
        return 0;
    }
}
