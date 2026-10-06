#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ampr_emu"
CONFIG = ROOT / "include" / "ampr_emu_config.h"
PACK = ROOT / "src" / "ampr_emu_pack.cpp"
HOOK = ROOT / "src" / "ampr_libkernel_hook.cpp"


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

#ifndef AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
// Low-volume, always-on diagnostics for backing-pack compatibility testing.
#define AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS 1
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
static std::atomic<uint64_t> g_backingFallbackAttempts{0};
static std::atomic<uint64_t> g_backingFallbackSuccesses{0};
static std::atomic<uint64_t> g_backingFallbackFailures{0};

static bool retry_backing_request_with_pread(
    const SceKernelAioRWRequest& request,
    SceKernelAioResult& result,
    int priorError) {
    const int64_t priorReturnValue = result.returnValue;
    const uint64_t attempt =
        g_backingFallbackAttempts.fetch_add(1, std::memory_order_relaxed) + 1;

#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    // Keep successful diagnostic output bounded while always logging failures.
    if (attempt <= 64) {
        AMPR_CRITICAL_LOGF(
            "[AMPR_IO] fallback.enter seq=%llu fd=%d off=0x%llx req=0x%llx aio_ret=%lld prior=0x%x",
            (unsigned long long)attempt,
            request.fd,
            (unsigned long long)request.offset,
            (unsigned long long)request.nbyte,
            (long long)priorReturnValue,
            priorError);
    }
#endif

    if (request.nbyte == 0) {
        result.returnValue = 0;
        g_backingFallbackSuccesses.fetch_add(1, std::memory_order_relaxed);
        return true;
    }
    if (request.fd < 0 || !request.buf || request.offset < 0) {
        g_backingFallbackFailures.fetch_add(1, std::memory_order_relaxed);
        AMPR_CRITICAL_LOGF(
            "[AMPR_IO] fallback.reject seq=%llu fd=%d off=0x%llx req=0x%llx aio_ret=%lld prior=0x%x",
            (unsigned long long)attempt,
            request.fd,
            (unsigned long long)request.offset,
            (unsigned long long)request.nbyte,
            (long long)priorReturnValue,
            priorError);
        return false;
    }

    errno = 0;
    const bool ok = pread_exact(
        request.fd,
        request.buf,
        request.nbyte,
        static_cast<uint64_t>(request.offset));
    const int fallbackErrno = errno;

    if (ok) {
        const uint64_t successes =
            g_backingFallbackSuccesses.fetch_add(1, std::memory_order_relaxed) + 1;
        result.returnValue = static_cast<int64_t>(request.nbyte);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        if (attempt <= 64) {
            AMPR_CRITICAL_LOGF(
                "[AMPR_IO] fallback.pread.ok seq=%llu ok=%llu fd=%d off=0x%llx req=0x%llx aio_ret=%lld prior=0x%x",
                (unsigned long long)attempt,
                (unsigned long long)successes,
                request.fd,
                (unsigned long long)request.offset,
                (unsigned long long)request.nbyte,
                (long long)priorReturnValue,
                priorError);
        }
#endif
        return true;
    }

    const uint64_t failures =
        g_backingFallbackFailures.fetch_add(1, std::memory_order_relaxed) + 1;
    AMPR_CRITICAL_LOGF(
        "[AMPR_IO] fallback.pread.fail seq=%llu fail=%llu fd=%d off=0x%llx req=0x%llx aio_ret=%lld prior=0x%x errno=%d",
        (unsigned long long)attempt,
        (unsigned long long)failures,
        request.fd,
        (unsigned long long)request.offset,
        (unsigned long long)request.nbyte,
        (long long)priorReturnValue,
        priorError,
        fallbackErrno);
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

identity_anchor = """    if (debugOut(AMPR_EMU_DEBUG_LOG_KERNEL_OUT_CHANNEL, line) < 0) {
        // Permit a later explicit install attempt to retry a failed system-log
"""
identity_insert = """    if (debugOut(AMPR_EMU_DEBUG_LOG_KERNEL_OUT_CHANNEL, line) < 0) {
        // Permit a later explicit install attempt to retry a failed system-log
"""
# Add an unmistakable runtime marker immediately after the normal module identity
# has been emitted successfully.
marker_anchor = """    if (debugOut(AMPR_EMU_DEBUG_LOG_KERNEL_OUT_CHANNEL, line) < 0) {
        // Permit a later explicit install attempt to retry a failed system-log
        // write without ever involving the file logger.
        g_moduleIdentityLogged.store(0, std::memory_order_release);
    }
}
"""
marker_insert = """    if (debugOut(AMPR_EMU_DEBUG_LOG_KERNEL_OUT_CHANNEL, line) < 0) {
        // Permit a later explicit install attempt to retry a failed system-log
        // write without ever involving the file logger.
        g_moduleIdentityLogged.store(0, std::memory_order_release);
        return;
    }
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    debugOut(AMPR_EMU_DEBUG_LOG_KERNEL_OUT_CHANNEL,
             "[AMPR_IO] backing-io-debug=1 aio-pread-fallback=1\\n");
#endif
}
"""
replace_once(HOOK, marker_anchor, marker_insert)

print("Applied general AMPR backing AIO -> exact pread compatibility fallback + diagnostics")
