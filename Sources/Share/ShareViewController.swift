import Cocoa
import OSLog
import UniformTypeIdentifiers

private let logger = Logger(subsystem: "com.xuxu.wxtoob.share", category: "share")

// 沙盒里 FileManager 的 home 指向容器目录，这里要真实的用户目录；Share.entitlements 只放行它。
private let dataDir = URL(fileURLWithPath: String(cString: getpwuid(getuid())!.pointee.pw_dir))
    .appending(path: "Library/Application Support/WxToOb")
private let logFile = dataDir.appending(path: "share.log")
private let incomingDir = dataDir.appending(path: "incoming")
private let queueDir = dataDir.appending(path: "queue")

private func stamp(_ format: String) -> String {
    let formatter = DateFormatter()
    formatter.dateFormat = format
    return formatter.string(from: .now)
}

private func log(_ message: String) {
    logger.log("\(message, privacy: .public)")
    let line = "[\(stamp("yyyy-MM-dd HH:mm:ss"))] \(message)\n"
    do {
        try FileManager.default.createDirectory(at: dataDir, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: logFile.path) {
            FileManager.default.createFile(atPath: logFile.path, contents: nil)
        }
        let handle = try FileHandle(forWritingTo: logFile)
        defer { try? handle.close() }
        try handle.seekToEnd()
        try handle.write(contentsOf: Data(line.utf8))
    } catch {
        logger.error("写日志失败 \(logFile.path, privacy: .public): \(error, privacy: .public)")
    }
}

/// 先写到 incoming 再改名进 queue：launchd 盯着 queue，只能让它看到写完整的文件。
private func enqueue(_ source: URL) throws -> URL {
    let fm = FileManager.default
    try fm.createDirectory(at: incomingDir, withIntermediateDirectories: true)
    try fm.createDirectory(at: queueDir, withIntermediateDirectories: true)
    let name = "\(stamp("yyyyMMdd-HHmmss"))-\(UUID().uuidString.prefix(8)).zip"
    let staged = incomingDir.appending(path: name)
    try fm.copyItem(at: source, to: staged)
    let queued = queueDir.appending(path: name)
    try fm.moveItem(at: staged, to: queued)
    return queued
}

// 系统按 Info.plist 的 NSExtensionPrincipalClass 找类，@objc 去掉模块名前缀。
@objc(ShareViewController)
final class ShareViewController: NSViewController {
    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 1, height: 1))
        let context = extensionContext!
        let providers = (context.inputItems as! [NSExtensionItem]).flatMap { $0.attachments ?? [] }
        log("收到分享 attachments=\(providers.count)")
        // 激活规则保证恰好有一个 zip。
        let provider = providers.first { $0.hasItemConformingToTypeIdentifier(UTType.zip.identifier) }!
        provider.loadFileRepresentation(forTypeIdentifier: UTType.zip.identifier) { url, error in
            guard let url else {
                log("读取 zip 失败: \(error!)")
                context.cancelRequest(withError: error!)
                return
            }
            // url 只在回调期间有效，必须在这里复制走。
            do {
                let queued = try enqueue(url)
                log("已入队 \(queued.lastPathComponent)（来源 \(url.lastPathComponent)）")
                context.completeRequest(returningItems: nil)
            } catch {
                log("入队失败 来源=\(url.path): \(error)")
                context.cancelRequest(withError: error)
            }
        }
    }
}
