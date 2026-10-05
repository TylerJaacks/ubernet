# uedec

Decompiles UnrealScript classes from SMNC packages using [UELib](https://github.com/EliotVU/Unreal-Library). Needs the .NET 8 SDK.

1. Clone UELib so the path `../../../uelib/src` is valid from this folder, or edit that path in `uedec.csproj`.
2. Build with `dotnet build -c Release`.
3. Decompress the package first, since UELib doesn't handle the game's compression: `python ../ue3pkg.py` (see `decompress()`). The `.dec.upk` files made in this session were written with the chunk table removed and the header's remaining fields kept.
4. Run `dotnet bin/Release/net8.0/uedec.dll Startup.dec.upk out/ MNCClient`. The last argument is an optional filter on the class path.

The class that does the client's login and backend work is `MNCClient.HWebInterfaceClient`, which is in `Startup.upk`. The login screen is `GFxLogin`, in `MNCGame.upk`.
