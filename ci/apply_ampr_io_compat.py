#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ampr_emu"
CONFIG = ROOT / "include" / "ampr_emu_config.h"
PACK = ROOT / "src" / "ampr_emu_pack.cpp"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected exactly one anchor, found {count}: {old[:80]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


config_anchor = """#ifndef AMPR_EMU_PACK_TELEMETRY
// Collect pack counters and worker/AIO latency samples used only by diagnostic
"""
config_insert = """#ifndef AMPR_EMU_PACK_AIO_PREAD_FALLBACK
// Retry failed or short backing-pack AIO reads synchronously with pread().
// This is a backend-compatibility safety net, not a title-specific workaround.
#define AMPR_EMU_PACK_AIO_PREAD_FALLBACK 1
#endif

#ifndef AMPR_EMU_PACK_TELEMETRY
// Collect pack counters and worker/AIO latency samples used only by diagnostic
"""
replace_once(CONFIG, config_anchor, config_insert)

helper_anchor = """static bool bytes_equal(const void* a, const void* b, size_t size) {
    return std::memcmp(a, b, size) == 0;
}
"""
helper_insert = """#if AMPR_EMU_PACK_AIO_PREAD_FALLBACK
static bool retry_backing_request_with_pread(
    const SceKernelAioRWRequest& request,
    SceKernelAioResult& result,
    int priorError) {
    if (request.nbyte == 0) {
        result.returnValue = 0;
        return true;
    }
    if (request.fd < 0 || !request.buf || request.offset < 0) {
        return false;
    }

    const bool ok = pread_exact(
        request.fd,
        request.buf,
        request.nbyte,
        static_cast<uint64_t>(request.offset));

    if (ok) {
        result.returnValue = static_cast<int64_t>(request.nbyte);
        AMPR_LOGF(
            "apr.pack.backing.pread-fallback.ok fd=%d off=0x%llx bytes=0x%llx prior=0x%x",
            request.fd,
            (unsigned long long)request.offset,
            (unsigned long long)request.nbyte,
            priorError);
        return true;
    }

    AMPR_CRITICAL_LOGF(
        "apr.pack.backing.pread-fallback.fail fd=%d off=0x%llx bytes=0x%llx prior=0x%x errno=%d",
        request.fd,
        (unsigned long long)request.offset,
        (unsigned long long)request.nbyte,
        priorError,
        errno);
    return false;
}
#endif

static bool bytes_equal(const void* a, const void* b, size_t size) {
    return std::memcmp(a, b, size) == 0;
}
"""
replace_once(PACK, helper_anchor, helper_insert)

mandatory_anchor = """static int finish_mandatory_page_group(ReadPipelineContext& pipeline) {
    PackState& state = pack_state();
    const int completionError = pipeline.nativeIoError;
    int groupError = completionError;
    release_mandatory_fds(pipeline);
"""
mandatory_insert = """static int finish_mandatory_page_group(ReadPipelineContext& pipeline) {
    PackState& state = pack_state();
    int completionError = pipeline.nativeIoError;
    int groupError = completionError;

#if AMPR_EMU_PACK_AIO_PREAD_FALLBACK
    if (completionError != SCE_KERNEL_ERROR_ECANCELED) {
        const int groupPriorError = completionError;
        bool fallbackFailed = false;

        for (size_t requestIndex = 0;
             requestIndex < pipeline.mandatoryRequestCount;
             ++requestIndex) {
            const SceKernelAioRWRequest& request =
                pipeline.mandatoryRequests[requestIndex];
            SceKernelAioResult& result =
                pipeline.mandatoryResults[requestIndex];

            int requestError = groupPriorError;
            if (requestError == 0 &&
                result.returnValue != static_cast<int64_t>(request.nbyte)) {
                requestError = result.returnValue < 0
                    ? static_cast<int>(result.returnValue)
                    : SCE_KERNEL_ERROR_EIO;
            }

            if (requestError != 0 &&
                !retry_backing_request_with_pread(
                    request, result, requestError)) {
                result.returnValue = requestError;
                fallbackFailed = true;
            }
        }

        if (!fallbackFailed) {
            completionError = 0;
            groupError = 0;
        }
    }
#endif

    release_mandatory_fds(pipeline);
"""
replace_once(PACK, mandatory_anchor, mandatory_insert)

window_anchor = """    if (error == 0 &&
        pipeline.nativeResult.returnValue != static_cast<int64_t>(range.length)) {
        error = pipeline.nativeResult.returnValue < 0
                    ? static_cast<int>(pipeline.nativeResult.returnValue)
                    : SCE_KERNEL_ERROR_EIO;
    }
    if (pipeline.packFd >= 0) {
"""
window_insert = """    if (error == 0 &&
        pipeline.nativeResult.returnValue != static_cast<int64_t>(range.length)) {
        error = pipeline.nativeResult.returnValue < 0
                    ? static_cast<int>(pipeline.nativeResult.returnValue)
                    : SCE_KERNEL_ERROR_EIO;
    }

#if AMPR_EMU_PACK_AIO_PREAD_FALLBACK
    if (error != 0 && error != SCE_KERNEL_ERROR_ECANCELED &&
        pipeline.packFd >= 0) {
        const int priorError = error;
        if (retry_backing_request_with_pread(
                pipeline.nativeRequest,
                pipeline.nativeResult,
                priorError)) {
            error = 0;
        }
    }
#endif

    if (pipeline.packFd >= 0) {
"""
replace_once(PACK, window_anchor, window_insert)

print("Applied general AMPR backing AIO -> exact pread compatibility fallback")
