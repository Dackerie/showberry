import Foundation

let bundleURL = Bundle.main.bundleURL
let resourcesDir = bundleURL.appendingPathComponent("Contents/Resources")
FileManager.default.changeCurrentDirectoryPath(resourcesDir.path)

let execPath = resourcesDir.appendingPathComponent("showberry/showberry").path
let args: [UnsafeMutablePointer<CChar>?] = [
    strdup("showberry"),
    nil
]

execv(execPath, args)
