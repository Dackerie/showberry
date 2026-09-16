import Foundation

let bundleURL = Bundle.main.bundleURL
let resourcesDir = bundleURL.appendingPathComponent("Contents/Resources")
FileManager.default.changeCurrentDirectoryPath(resourcesDir.path)

let showberryDir = resourcesDir.appendingPathComponent("showberry").path
let internalDir = resourcesDir.appendingPathComponent("showberry/_internal").path

// Export DYLD fallback library paths
let currentFallback = ProcessInfo.processInfo.environment["DYLD_FALLBACK_LIBRARY_PATH"] ?? ""
let newFallback = [internalDir, showberryDir, currentFallback].filter { !$0.isEmpty }.joined(separator: ":")
setenv("DYLD_FALLBACK_LIBRARY_PATH", newFallback, 1)

let execPath = resourcesDir.appendingPathComponent("showberry/showberry").path
var args: [UnsafeMutablePointer<CChar>?] = [
    strdup("showberry")
]
for arg in CommandLine.arguments.dropFirst() {
    args.append(strdup(arg))
}
args.append(nil)

execv(execPath, args)
