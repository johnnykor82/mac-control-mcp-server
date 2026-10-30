import AppKit
import Darwin
import ApplicationServices
import CoreGraphics
import Foundation
import ImageIO
import ScreenCaptureKit

enum AgentError: Error, CustomStringConvertible {
    case invalid(String)
    var description: String {
        switch self { case .invalid(let s): return s }
    }
}

// Paths are selected on the destination Mac, never baked into the signed app.
struct GUIRuntimePaths {
    let dataRoot: String
    var socket: String { dataRoot + "/run/maccontrol-gui.sock" }
    var capturePrefix: String { dataRoot + "/run/gui-captures/" }

    static func resolve(arguments: [String], environment: [String: String], home: String) throws -> GUIRuntimePaths {
        let indices = arguments.indices.filter { arguments[$0] == "--data-root" }
        guard indices.count <= 1 else { throw AgentError.invalid("Duplicate --data-root") }
        let selected: String
        if let index = indices.first {
            guard index + 1 < arguments.count else { throw AgentError.invalid("Missing --data-root value") }
            selected = arguments[index + 1]
        } else {
            let override = (environment["MAC_CONTROL_DATA_ROOT"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            selected = override.isEmpty ? home + "/MacControlMCP/data" : override
        }
        let expanded = (selected as NSString).expandingTildeInPath
        guard expanded.hasPrefix("/"), !expanded.utf8.contains(0) else {
            throw AgentError.invalid("GUI data root must be an absolute path")
        }
        let paths = GUIRuntimePaths(dataRoot: URL(fileURLWithPath: expanded).standardizedFileURL.path)
        guard paths.socket.utf8.count < 100 else {
            throw AgentError.invalid("GUI Unix socket path exceeds 99 UTF-8 bytes; choose a shorter data root")
        }
        return paths
    }
}

let GUI_RUNTIME_PATHS = Result {
    try GUIRuntimePaths.resolve(arguments: CommandLine.arguments,
        environment: ProcessInfo.processInfo.environment,
        home: FileManager.default.homeDirectoryForCurrentUser.path)
}

func argument(_ req: [String: Any], _ key: String, _ fallback: String = "") -> String {
    return req[key] as? String ?? fallback
}
func number(_ req: [String: Any], _ key: String, _ fallback: Double = 0) -> Double {
    if let n = req[key] as? NSNumber { return n.doubleValue }
    return fallback
}
func flag(_ req: [String: Any], _ key: String) -> Bool {
    return req[key] as? Bool ?? false
}
func serialize(_ data: [String: Any]) {
    let json: Data
    do {
        json = try JSONSerialization.data(withJSONObject: data, options: [.sortedKeys, .fragmentsAllowed])
        print(String(data: json, encoding: .utf8) ?? "{}")
    } catch {
        print("{\"error\":\"JSON serialization failed\"}")
    }
}
func requireAccess() throws {
    guard AXIsProcessTrusted() else {
        throw AgentError.invalid("Accessibility permission not granted to MacControlGUI")
    }
}
func displayInfo() -> [[String: Any]] {
    var ids = [CGDirectDisplayID](repeating: 0, count: 16)
    var count: UInt32 = 0
    let result = CGGetActiveDisplayList(16, &ids, &count)
    guard result == .success else { return [] }
    return ids.prefix(Int(count)).map { id in
        let b = CGDisplayBounds(id)
        return [
            "id": Int(id), "main": CGDisplayIsMain(id) != 0,
            "x": b.origin.x, "y": b.origin.y,
            "width": b.size.width, "height": b.size.height,
            "pixel_width": CGDisplayPixelsWide(id),
            "pixel_height": CGDisplayPixelsHigh(id),
        ]
    }
}

func windowInfo() -> [[String:Any]] {
    let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    guard let all = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else { return [] }
    return all.prefix(150).compactMap { window in
        let layer = window[kCGWindowLayer as String] as? Int ?? 0
        if layer != 0 { return nil }
        let bounds = window[kCGWindowBounds as String] as? [String: Any] ?? [:]
        let name = window[kCGWindowName as String] as? String ?? ""
        let owner = window[kCGWindowOwnerName as String] as? String ?? ""
        return [
            "window_id": window[kCGWindowNumber as String] ?? 0,
            "pid": window[kCGWindowOwnerPID as String] ?? 0,
            "name": name.prefix(180).description,
            "app": owner.prefix(100).description,
            "bounds": bounds,
        ]
    }
}
func axAttr(_ item: AXUIElement, _ attribute: String) -> CFTypeRef? {
    var value: CFTypeRef?
    let status = AXUIElementCopyAttributeValue(item, attribute as CFString, &value)
    return status == .success ? value : nil
}
func axString(_ item: AXUIElement, _ attribute: String) -> String {
    guard let value = axAttr(item, attribute) else { return "" }
    return String(describing: value).prefix(150).description
}
func axPoint(_ value: CFTypeRef?) -> CGPoint? {
    guard let value, CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
    let ax = value as! AXValue
    guard AXValueGetType(ax) == .cgPoint else { return nil }
    var p = CGPoint.zero
    guard AXValueGetValue(ax, .cgPoint, &p) else { return nil }
    return p
}
func axSize(_ value: CFTypeRef?) -> CGSize? {
    guard let value, CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
    let ax = value as! AXValue
    guard AXValueGetType(ax) == .cgSize else { return nil }
    var p = CGSize.zero
    guard AXValueGetValue(ax, .cgSize, &p) else { return nil }
    return p
}
func axChildren(_ item: AXUIElement) -> [AXUIElement] {
    guard let children = axAttr(item, kAXChildrenAttribute as String) as? [AXUIElement] else { return [] }
    return Array(children.prefix(100))
}
func inspectUI(_ pid: pid_t, maxDepth: Int, maxNodes: Int) -> [[String: Any]] {
    let app = AXUIElementCreateApplication(pid)
    AXUIElementSetMessagingTimeout(app, 1.0)
    var nodes = [[String:Any]]()
    var visited = Set<String>()
    func walk(_ item: AXUIElement, depth: Int) {
        if nodes.count >= maxNodes || depth > maxDepth { return }
        let marker = "\(Unmanaged.passUnretained(item).toOpaque())"
        if visited.contains(marker) { return }
        visited.insert(marker)
        let role = axString(item, kAXRoleAttribute as String)
        let title = axString(item, kAXTitleAttribute as String)
        let subrole = axString(item, kAXSubroleAttribute as String)
        var entry: [String:Any] = ["index": nodes.count, "depth": depth,
                                   "role": role, "subrole": subrole,
                                   "title": title]
        if let point = axPoint(axAttr(item, kAXPositionAttribute as String)),
           let size = axSize(axAttr(item, kAXSizeAttribute as String)) {
            entry["frame"] = ["x": point.x, "y": point.y,
                              "width": size.width, "height": size.height]
        }
        // Never read kAXValueAttribute: it may contain password or private text.
        nodes.append(entry)
        if role.contains("Secure") || subrole.contains("Secure") { return }
        for child in axChildren(item) { walk(child, depth: depth + 1) }
    }
    walk(app, depth: 0)
    return nodes
}
func focusedApp() -> [String: Any] {
    guard let app = NSWorkspace.shared.frontmostApplication else { return [:] }
    return ["pid": Int(app.processIdentifier),
            "name": app.localizedName ?? "",
            "bundle_id": app.bundleIdentifier ?? ""]
}
func capture(_ req: [String:Any]) async throws -> [String:Any] {
    guard CGPreflightScreenCaptureAccess() else {
        throw AgentError.invalid("Screen Recording permission not granted to MacControlGUI")
    }
    let requestedId = CGDirectDisplayID(number(req, "display_id", 0))
    let id = requestedId == 0 ? CGMainDisplayID() : requestedId
    let shareable = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
    guard let display = shareable.displays.first(where: { $0.displayID == id }) else {
        throw AgentError.invalid("Display not available to ScreenCaptureKit")
    }
    let filter = SCContentFilter(display: display, excludingWindows: [])
    let config = SCStreamConfiguration()
    config.width = display.width
    config.height = display.height
    let shot = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
    let width = shot.width
    let height = shot.height
    let maxWidth = max(300, min(2000, Int(number(req, "max_width", 1200))))
    let factor = min(1.0, Double(maxWidth) / Double(width))
    let outputW = max(1, Int(Double(width) * factor))
    let outputH = max(1, Int(Double(height) * factor))
    let image: CGImage
    if factor < 1 {
        guard let ctx = CGContext(data: nil, width: outputW, height: outputH,
                                  bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue),
              let resized = {
                  ctx.interpolationQuality = .high
                  ctx.draw(shot, in: CGRect(x: 0, y: 0, width: outputW, height: outputH))
                  return ctx.makeImage()
              }() else {
            throw AgentError.invalid("Failed to resize image")
        }
        image = resized
    } else { image = shot }
    let destinationPath = argument(req, "destination")
    guard destinationPath.hasPrefix(try GUI_RUNTIME_PATHS.get().capturePrefix),
          destinationPath.hasSuffix(".jpg"),
          !destinationPath.contains("..") else {
        throw AgentError.invalid("Invalid capture path")
    }
    let dest = URL(fileURLWithPath: destinationPath)
    guard let imageDest = CGImageDestinationCreateWithURL(dest as CFURL,
                     "public.jpeg" as CFString, 1, nil) else {
        throw AgentError.invalid("Failed to initialize image output")
    }
    CGImageDestinationAddImage(imageDest, image,
        [kCGImageDestinationLossyCompressionQuality: 0.66] as CFDictionary)
    guard CGImageDestinationFinalize(imageDest) else {
        throw AgentError.invalid("Failed to save screenshot")
    }
    return ["file": destinationPath,
            "pixel_width": width, "pixel_height": height,
            "preview_width": outputW, "preview_height": outputH,
            "display_id": Int(id)]
}
func postMouse(_ kind: CGEventType, _ point: CGPoint, _ button: CGMouseButton = .left) throws {
    guard let event = CGEvent(mouseEventSource: nil, mouseType: kind,
                              mouseCursorPosition: point, mouseButton: button) else {
        throw AgentError.invalid("Failed to create mouse event")
    }
    event.post(tap: .cghidEventTap)
}
func keyCode(_ key: String) -> CGKeyCode? {
    let codes: [String:CGKeyCode] = [
        "a":0, "s":1, "d":2, "f":3, "h":4, "g":5, "z":6, "x":7, "c":8, "v":9,
        "b":11, "q":12, "w":13, "e":14, "r":15, "y":16, "t":17, "1":18,
        "2":19, "3":20, "4":21, "6":22, "5":23, "=":24, "9":25, "7":26,
        "-":27, "8":28, "0":29, "]":30, "o":31, "u":32, "[":33, "i":34,
        "p":35, "return":36, "enter":36, "l":37, "j":38, "'":39, "k":40,
        ";":41, "\\":42, ",":43, "/":44, "n":45, "m":46, ".":47,
        "tab":48, "space":49, "backspace":51, "escape":53, "cmd":55,
        "shift":56, "capslock":57, "option":58, "ctrl":59,
        "rightshift":60, "rightoption":61, "rightctrl":62,
        "f1":122, "f2":120, "f3":99, "f4":118, "f5":96, "f6":97,
        "f7":98, "f8":100, "f9":101, "f10":109, "f11":103, "f12":111,
        "home":115, "end":119, "pageup":116, "pagedown":121,
        "left":123, "right":124, "down":125, "up":126, "delete":117,
    ]
    return codes[key.lowercased()]
}
func press(_ req:[String:Any]) throws -> [String:Any] {
    let key = argument(req, "key").lowercased()
    guard let code = keyCode(key) else { throw AgentError.invalid("Unsupported key") }
    let modifiers = req["modifiers"] as? [String] ?? []
    var flags: CGEventFlags = []
    for modifier in modifiers {
        switch modifier.lowercased() {
        case "cmd", "command": flags.insert(.maskCommand)
        case "shift": flags.insert(.maskShift)
        case "ctrl", "control": flags.insert(.maskControl)
        case "option", "alt": flags.insert(.maskAlternate)
        default: throw AgentError.invalid("Unsupported modifier")
        }
    }
    guard let down = CGEvent(keyboardEventSource:nil, virtualKey:code, keyDown:true),
          let up = CGEvent(keyboardEventSource:nil, virtualKey:code, keyDown:false) else {
        throw AgentError.invalid("Failed to create keyboard events")
    }
    down.flags = flags
    up.flags = flags
    down.post(tap:.cghidEventTap)
    up.post(tap:.cghidEventTap)
    return ["key": key, "modifiers": modifiers, "sent":true]
}
func typeText(_ req:[String:Any]) throws -> [String:Any] {
    let text = argument(req, "text")
    guard text.utf16.count <= 2000 else {
        throw AgentError.invalid("Text too long")
    }
    let utf16 = Array(text.utf16)
    for i in stride(from:0, to:utf16.count, by:20) {
        let part = Array(utf16[i..<min(i+20, utf16.count)])
        guard let down=CGEvent(keyboardEventSource:nil,virtualKey:0,keyDown:true),
              let up=CGEvent(keyboardEventSource:nil,virtualKey:0,keyDown:false) else {
            throw AgentError.invalid("Keyboard event creation failed")
        }
        part.withUnsafeBufferPointer { ptr in
            down.keyboardSetUnicodeString(stringLength:ptr.count,unicodeString:ptr.baseAddress!)
            up.keyboardSetUnicodeString(stringLength:ptr.count,unicodeString:ptr.baseAddress!)
        }
        down.post(tap:.cghidEventTap)
        up.post(tap:.cghidEventTap)
        Thread.sleep(forTimeInterval:0.015)
    }
    return ["characters":text.count,"sent":true]
}
func activate(_ req:[String:Any]) throws -> [String:Any] {
    let bundleId=argument(req, "bundle_id")
    guard !bundleId.isEmpty else { throw AgentError.invalid("bundle_id required") }
    guard let app=NSRunningApplication.runningApplications(withBundleIdentifier:bundleId).first else {
        throw AgentError.invalid("Application not running")
    }
    let success=app.activate(options:[])
    return ["bundle_id":bundleId,"activated":success]
}
func dispatch(_ req:[String:Any]) async throws -> [String:Any] {
    let op=argument(req,"op")
    switch op {
    case "status":
        return ["accessibility_trusted":AXIsProcessTrusted(),
                "screen_capture_trusted":CGPreflightScreenCaptureAccess(),
                "frontmost":focusedApp(), "displays":displayInfo(),
                "gui_user":NSUserName()]
    case "request_accessibility":
        let axOption: [String: Any] = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
        return ["accessibility_trusted": AXIsProcessTrustedWithOptions(axOption as CFDictionary)]
    case "request_screen_capture":
        return ["screen_capture_trusted": CGRequestScreenCaptureAccess()]
    case "request_permissions":
        let axOption: [String: Any] = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
        let ax = AXIsProcessTrustedWithOptions(axOption as CFDictionary)
        let screen = CGRequestScreenCaptureAccess()
        return ["accessibility_trusted": ax, "screen_capture_trusted": screen]
    case "displays": return ["displays":displayInfo()]
    case "windows": return ["windows":windowInfo(), "frontmost":focusedApp()]
    case "ui_tree":
        try requireAccess()
        let pid=Int32(number(req,"pid",Double(NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0)))
        guard pid>0 else {throw AgentError.invalid("No application PID available")}
        return ["pid":pid, "nodes":inspectUI(pid,
                     maxDepth:max(1,min(7,Int(number(req,"max_depth",4)))),
                     maxNodes:max(5,min(200,Int(number(req,"max_nodes",120)))))]
    case "capture": return try await capture(req)
    case "mouse":
        try requireAccess()
        let x=number(req,"x"), y=number(req,"y")
        let point=CGPoint(x:x,y:y)
        switch argument(req,"action") {
        case "move": try postMouse(.mouseMoved,point)
        case "left_click","double_click":
            let times=argument(req,"action")=="double_click" ? 2 : 1
            for _ in 0..<times {
                try postMouse(.leftMouseDown,point)
                try postMouse(.leftMouseUp,point)
                Thread.sleep(forTimeInterval:0.05)
            }
        case "right_click":
            try postMouse(.rightMouseDown,point,.right)
            try postMouse(.rightMouseUp,point,.right)
        case "drag":
            let end=CGPoint(x:number(req,"end_x"),y:number(req,"end_y"))
            try postMouse(.leftMouseDown,point)
            for i in 1...12 {
                let f=CGFloat(i)/12
                try postMouse(.leftMouseDragged,CGPoint(x:x+(end.x-x)*f,
                                                       y:y+(end.y-y)*f))
                Thread.sleep(forTimeInterval:0.015)
            }
            try postMouse(.leftMouseUp,end)
        default: throw AgentError.invalid("Invalid mouse action")
        }
        return ["action":argument(req,"action"),"x":x,"y":y,"sent":true]
    case "scroll":
        try requireAccess()
        let dy=Int32(number(req,"dy",0)),dx=Int32(number(req,"dx",0))
        guard let event=CGEvent(scrollWheelEvent2Source:nil,units:.line,
                                wheelCount:2,wheel1:dy,wheel2:dx,wheel3:0) else {
            throw AgentError.invalid("Failed to create scroll event")
        }
        event.post(tap:.cghidEventTap)
        return ["dx":dx,"dy":dy,"sent":true]
    case "key":
        try requireAccess()
        return try press(req)
    case "type":
        try requireAccess()
        return try typeText(req)
    case "activate":
        try requireAccess()
        return try activate(req)
    default: throw AgentError.invalid("Unknown GUI operation")
    }
}

func encodedResponse(_ obj:[String:Any]) -> Data {
    return (try? JSONSerialization.data(withJSONObject: obj,options:[.sortedKeys])) ?? Data("{\"ok\":false,\"error\":\"Serialization failed\"}".utf8)
}

func handleRequest(_ payload: Data) async -> Data {
    do {
        guard payload.count <= 8000 else {
            throw AgentError.invalid("Request exceeds 8KiB")
        }
        guard let input=try JSONSerialization.jsonObject(with:payload) as? [String:Any] else {
            throw AgentError.invalid("Expected JSON object")
        }
        let output=try await dispatch(input)
        return encodedResponse(["ok":true,"data":output])
    } catch {
        return encodedResponse(["ok":false,"error":String(describing:error)])
    }
}

func startGUIServer() async throws {
    let GUI_SOCKET_PATH = try GUI_RUNTIME_PATHS.get().socket
    let parent=(GUI_SOCKET_PATH as NSString).deletingLastPathComponent
    try FileManager.default.createDirectory(atPath:parent,withIntermediateDirectories:true)
    if FileManager.default.fileExists(atPath:GUI_SOCKET_PATH) {
        // Remove a leftover socket only when no server is attached.
        let probe = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        defer { Darwin.close(probe) }
        var testAddr=sockaddr_un()
        testAddr.sun_family=sa_family_t(AF_UNIX)
        let testBytes=Array(GUI_SOCKET_PATH.utf8CString)
        guard testBytes.count <= MemoryLayout.size(ofValue:testAddr.sun_path) else {
            throw AgentError.invalid("Socket path too long")
        }
        withUnsafeMutableBytes(of:&testAddr.sun_path) { bytes in
            for i in testBytes.indices { bytes[i]=UInt8(bitPattern:testBytes[i]) }
        }
        let reachable=withUnsafePointer(to:&testAddr) {
            $0.withMemoryRebound(to:sockaddr.self,capacity:1) {
                Darwin.connect(probe,$0,socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        } == 0
        if reachable { throw AgentError.invalid("GUI helper already running") }
        _ = unlink(GUI_SOCKET_PATH)
    }
    let server = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
    guard server >= 0 else { throw AgentError.invalid("Socket creation failed") }
    defer { Darwin.close(server); _ = unlink(GUI_SOCKET_PATH) }
    var address=sockaddr_un()
    address.sun_family=sa_family_t(AF_UNIX)
    let bytes=Array(GUI_SOCKET_PATH.utf8CString)
    guard bytes.count <= MemoryLayout.size(ofValue:address.sun_path) else {
        throw AgentError.invalid("Socket path too long")
    }
    withUnsafeMutableBytes(of:&address.sun_path) { view in
        for i in bytes.indices { view[i]=UInt8(bitPattern:bytes[i]) }
    }
    let rc=withUnsafePointer(to:&address) {
        $0.withMemoryRebound(to:sockaddr.self,capacity:1) {
            Darwin.bind(server,$0,socklen_t(MemoryLayout<sockaddr_un>.size))
        }
    }
    guard rc == 0 else { throw AgentError.invalid("Socket bind failed errno \(errno)") }
    _ = chmod(GUI_SOCKET_PATH,0o600)
    guard Darwin.listen(server,8) == 0 else {
        throw AgentError.invalid("Socket listen failed")
    }
    while true {
        let client = Darwin.accept(server,nil,nil)
        if client < 0 { continue }
        defer { Darwin.close(client) }
        var peerUid=uid_t.max
        var peerGid=gid_t.max
        guard getpeereid(client,&peerUid,&peerGid) == 0 && peerUid == geteuid() else {
            continue
        }
        var buffer=[UInt8](repeating:0,count:4096)
        var data=Data()
        while data.count <= 8000 {
            let n=Darwin.read(client,&buffer,buffer.count)
            if n<=0 { break }
            data.append(contentsOf:buffer.prefix(n))
        }
        let response=await handleRequest(data)
        response.withUnsafeBytes { raw in
            guard let start=raw.baseAddress else {return}
            var cursor=0
            while cursor<raw.count {
                let n=Darwin.write(client,start.advanced(by:cursor),raw.count-cursor)
                if n<=0 {break}
                cursor += n
            }
        }
    }
}

@main
struct Program {
    static func main() async {
        do {
            _ = try GUI_RUNTIME_PATHS.get()
            if CommandLine.arguments.contains("--serve") {
                try await startGUIServer()
                return
            }
            let data=FileHandle.standardInput.readDataToEndOfFile()
            guard let input=try JSONSerialization.jsonObject(with:data) as? [String:Any] else {
                throw AgentError.invalid("Expected JSON input object")
            }
            let output=try await dispatch(input)
            serialize(["ok":true,"data":output])
        } catch {
            serialize(["ok":false,"error":String(describing:error)])
            exit(2)
        }
    }
}
