import AppKit
import Foundation

// Internal implementation of existing gui_type. The owner's clipboard contents
// remain in memory only and are never written to disk, logged, or returned.
func run() throws {
    guard let line = readLine(),
          let payload = line.data(using: .utf8),
          let request = try JSONSerialization.jsonObject(with: payload) as? [String: Any],
          let text = request["text"] as? String,
          text.utf16.count <= 2000 else {
        throw NSError(domain: "GuiPaste", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid input"])
    }

    let pasteboard = NSPasteboard.general
    var snapshot: [NSPasteboardItem] = []
    var total = 0
    for item in pasteboard.pasteboardItems ?? [] {
        let copy = NSPasteboardItem()
        for type in item.types {
            guard let bytes = item.data(forType: type) else {
                throw NSError(domain: "GuiPaste", code: 2,
                              userInfo: [NSLocalizedDescriptionKey: "Cannot preserve clipboard item"])
            }
            total += bytes.count
            guard total <= 32 * 1024 * 1024 else {
                throw NSError(domain: "GuiPaste", code: 3,
                              userInfo: [NSLocalizedDescriptionKey: "Clipboard too large to preserve"])
            }
            copy.setData(bytes, forType: type)
        }
        snapshot.append(copy)
    }

    pasteboard.clearContents()
    guard pasteboard.setString(text, forType: .string) else {
        // Recover the original clipboard before reporting failure.
        pasteboard.clearContents()
        if !snapshot.isEmpty { _ = pasteboard.writeObjects(snapshot) }
        throw NSError(domain: "GuiPaste", code: 4,
                      userInfo: [NSLocalizedDescriptionKey: "Failed to set temporary text"])
    }
    let revision = pasteboard.changeCount
    FileHandle.standardOutput.write(Data("READY\n".utf8))
    _ = readLine() // DONE, or EOF if caller exits; do not retain text beyond this.

    // Do not overwrite an independent clipboard change by the Mac owner.
    if pasteboard.changeCount == revision {
        pasteboard.clearContents()
        let writeOK = snapshot.isEmpty || pasteboard.writeObjects(snapshot)
        let restoredItems = pasteboard.pasteboardItems ?? []
        var verified = writeOK && restoredItems.count == snapshot.count
        if verified {
            for (expected, actual) in zip(snapshot, restoredItems) {
                if Set(expected.types) != Set(actual.types) {
                    verified = false
                    break
                }
                for type in expected.types {
                    if expected.data(forType: type) != actual.data(forType: type) {
                        verified = false
                        break
                    }
                }
                if !verified { break }
            }
        }
        FileHandle.standardOutput.write(Data(
            (verified ? "RESTORED\n" : "RESTORE_UNVERIFIED\n").utf8))
    } else {
        FileHandle.standardOutput.write(Data("CHANGED_BY_ANOTHER_PROCESS\n".utf8))
    }
}

do {
    try run()
} catch {
    // Intentionally omit exception details to avoid logging clipboard content.
    FileHandle.standardOutput.write(Data("ERROR\n".utf8))
    exit(1)
}
