import Foundation

let bundleURL = Bundle.main.bundleURL
let resourcesDir = bundleURL.appendingPathComponent("Contents/Resources")
FileManager.default.changeCurrentDirectoryPath(resourcesDir.path)

let execPath = resourcesDir.appendingPathComponent("showberry/showberry").path
var args: [UnsafeMutablePointer<CChar>?] = [
    strdup("showberry")
]
for arg in CommandLine.arguments.dropFirst() {
    args.append(strdup(arg))
}
args.append(nil)

execv(execPath, args)
