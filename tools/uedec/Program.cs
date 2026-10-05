using System; using System.IO; using System.Linq; using UELib; using UELib.Core;
class P {
  static void Main(string[] a) {
    string path=a[0], outDir=a[1], filter=a.Length>2?a[2]:null;
    var pkg=UnrealLoader.LoadPackage(path, FileAccess.Read);
    pkg.InitializePackage();
    Console.WriteLine($"{pkg.PackageName} v{pkg.Version}/{pkg.LicenseeVersion} objects={pkg.Objects.Count}");
    int n=0, fail=0;
    foreach (var cls in pkg.Objects.OfType<UClass>()) {
      string full=cls.GetPath();
      if (filter!=null && !full.Contains(filter)) continue;
      string outer=cls.Outer?.Name ?? pkg.PackageName;
      string dir=Path.Combine(outDir, outer); Directory.CreateDirectory(dir);
      string text;
      try { cls.Load(); text=cls.Decompile(); n++; }
      catch(Exception e){ text="// DECOMPILE FAILED: "+e; fail++; }
      File.WriteAllText(Path.Combine(dir, cls.Name+".uc"), text);
    }
    Console.WriteLine($"decompiled {n} classes, {fail} failed");
  }
}
