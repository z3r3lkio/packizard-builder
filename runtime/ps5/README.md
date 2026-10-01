# Packizard PS5 Runtime

Packizard keeps the PS5-side compatibility runtime source in this repository so desktop builds no longer depend on obtaining that source from the Lazy_AMPR repository.

The runtime must preserve the `sceAmpr*` ABI and the compatibility filename `libSceAmpr.sprx` because games can import those names directly. Those names are an ABI contract, not product branding. The product-facing component is **Packizard PS5 Runtime**.

`packizard_ps5_runtime.tar.xz` contains the PS5 runtime source, headers, payload-SDK build files, LZ4 source needed by the runtime and the applicable GPL license. Its SHA-256 is pinned in `ci/packizard_ps5_runtime.py`.

To build the compatibility runtime on a machine with the PS5 payload SDK:

```bash
cd packizard_runtime/ps5/packizard_ps5_runtime
PS5_PAYLOAD_SDK=/opt/ps5-payload-sdk ./build_packizard_runtime.sh
```

The output used by packaged games is `out/packizard/libSceAmpr.sprx`.

The source currently retains portions originating in `ampr_emu`; therefore its GPL attribution must remain until those portions are independently replaced. Removing the attribution before replacing the code would misstate provenance.
