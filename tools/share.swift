// 不打开微信，直接把一个 zip 交给「存到 Obsidian」分享扩展，用来本机自测。
// 用法：swift tools/share.swift <微信导出的.zip>
import AppKit

let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let service = NSSharingService.sharingServices(forItems: [url]).first(where: { $0.title == "存到 Obsidian" }) else {
    print("系统分享列表里没有「存到 Obsidian」，先运行 ./build.sh")
    exit(1)
}
service.perform(withItems: [url])
// 扩展在别的进程里异步运行，留几秒让它收完再退出。
RunLoop.main.run(until: .now.addingTimeInterval(5))
print("已交给扩展，看 ~/Library/Application Support/WxToOb/share.log 和 process.log")
