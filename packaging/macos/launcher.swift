import Foundation
import Cocoa

// Ensure macOS registers process as regular GUI app with Dock icon and focus
let nsApp = NSApplication.shared
nsApp.setActivationPolicy(.regular)
nsApp.activate(ignoringOtherApps: true)

let bundleURL = Bundle.main.bundleURL
let resourcesDir = bundleURL.appendingPathComponent("Contents/Resources")
FileManager.default.changeCurrentDirectoryPath(resourcesDir.path)

let showberryDir = resourcesDir.appendingPathComponent("showberry").path
let internalDir = resourcesDir.appendingPathComponent("showberry/_internal").path
let shareDir = resourcesDir.appendingPathComponent("share").path
let showberryShareDir = resourcesDir.appendingPathComponent("showberry/share").path

// Export DYLD fallback library paths
let currentFallback = ProcessInfo.processInfo.environment["DYLD_FALLBACK_LIBRARY_PATH"] ?? ""
let newFallback = [
    internalDir,
    showberryDir,
    "/opt/homebrew/lib",
    "/usr/local/lib",
    currentFallback
].filter { !$0.isEmpty }.joined(separator: ":")
setenv("DYLD_FALLBACK_LIBRARY_PATH", newFallback, 1)

// Export GSettings schema directories
let currentSchemaDir = ProcessInfo.processInfo.environment["GSETTINGS_SCHEMA_DIR"] ?? ""
let newSchemaDir = [
    resourcesDir.appendingPathComponent("share/glib-2.0/schemas").path,
    resourcesDir.appendingPathComponent("showberry/share/glib-2.0/schemas").path,
    resourcesDir.appendingPathComponent("showberry/data").path,
    resourcesDir.appendingPathComponent("data").path,
    "/opt/homebrew/share/glib-2.0/schemas",
    "/usr/local/share/glib-2.0/schemas",
    currentSchemaDir
].filter { !$0.isEmpty }.joined(separator: ":")
setenv("GSETTINGS_SCHEMA_DIR", newSchemaDir, 1)

// Export XDG data dirs for icons and desktop integrations
let currentXdgData = ProcessInfo.processInfo.environment["XDG_DATA_DIRS"] ?? ""
let newXdgData = [
    shareDir,
    showberryShareDir,
    "/opt/homebrew/share",
    "/usr/local/share",
    "/usr/share",
    currentXdgData
].filter { !$0.isEmpty }.joined(separator: ":")
setenv("XDG_DATA_DIRS", newXdgData, 1)

// Export GObject Introspection typelib paths
let currentTypelib = ProcessInfo.processInfo.environment["GI_TYPELIB_PATH"] ?? ""
let newTypelib = [
    resourcesDir.appendingPathComponent("share/girepository-1.0").path,
    resourcesDir.appendingPathComponent("showberry/share/girepository-1.0").path,
    resourcesDir.appendingPathComponent("showberry/_internal").path,
    "/opt/homebrew/lib/girepository-1.0",
    "/usr/local/lib/girepository-1.0",
    currentTypelib
].filter { !$0.isEmpty }.joined(separator: ":")
setenv("GI_TYPELIB_PATH", newTypelib, 1)

let pyinstallerExec = resourcesDir.appendingPathComponent("showberry/showberry").path
let venvPython = resourcesDir.appendingPathComponent("venv/bin/python3").path

if FileManager.default.fileExists(atPath: pyinstallerExec) {
    var args: [UnsafeMutablePointer<CChar>?] = [
        strdup("showberry")
    ]
    for arg in CommandLine.arguments.dropFirst() {
        args.append(strdup(arg))
    }
    args.append(nil)
    execv(pyinstallerExec, args)
} else if FileManager.default.fileExists(atPath: venvPython) {
    var args: [UnsafeMutablePointer<CChar>?] = [
        strdup("python3"),
        strdup("-m"),
        strdup("showberry.main")
    ]
    for arg in CommandLine.arguments.dropFirst() {
        args.append(strdup(arg))
    }
    args.append(nil)
    execv(venvPython, args)
} else {
    fputs("Error: Could not locate Showberry executable or bundled environment in \(resourcesDir.path)\n", stderr)
    exit(1)
}
