# Packizard PS5 Runtime

Packizard isolates the PS5-side compatibility runtime under `packizard_runtime/ps5/packizard_ps5_runtime` during source reconstruction. The runtime keeps the `sceAmpr*` ABI and compatibility filename `libSceAmpr.sprx` because games can import those names directly; they are compatibility contracts, not product branding.

During this migration milestone the source is copied out of the reconstructed compatibility tree and given a reproducible Packizard build wrapper. The next source-absorption milestone moves the complete validated source tree into this repository so reconstruction no longer needs the Lazy_AMPR baseline.

Build on a machine with `ps5-payload-sdk`:

```bash
cd packizard_runtime/ps5/packizard_ps5_runtime
PS5_PAYLOAD_SDK=/opt/ps5-payload-sdk ./build_packizard_runtime.sh
```

The compatibility output is `out/packizard/libSceAmpr.sprx`.

The current runtime implementation contains source derived from `ampr_emu`. Its GPL attribution must remain until those portions are independently replaced.
