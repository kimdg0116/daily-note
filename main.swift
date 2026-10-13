// 데일리 노트.app — 맥 앱 한 개 = 창 한 개. Dock 을 다시 누르면 새 창 대신 있던 창이 앞으로 온다 (일반 맥 앱처럼).
// 서버(server.py)가 안 떠 있으면 띄우고, 화면은 WKWebView 로 http://127.0.0.1:8749 을 연다.
import Cocoa
import WebKit

let PORT = 8749
let HOME_URL = URL(string: "http://127.0.0.1:\(PORT)/")!
let DIR = Bundle.main.bundleURL.deletingLastPathComponent()          // 앱이 들어 있는 프로젝트 폴더
let PYTHONS = ["/Library/Frameworks/Python.framework/Versions/3.14/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]

class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!

    func applicationDidFinishLaunching(_ n: Notification) {
        buildMenu()
        web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        web.navigationDelegate = self
        web.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 780, height: 980),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "DAILY"
        window.contentView = web
        window.center()
        window.setFrameAutosaveName("main")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        alive { up in
            if !up { self.startServer() }
            self.waitAndLoad(tries: 60)
        }
    }

    // Dock 을 누르면: 창이 닫혀 있으면 다시 보이고, 있으면 앞으로
    func applicationShouldHandleReopen(_ s: NSApplication, hasVisibleWindows f: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { false }

    // ⌘Q 직전에 아직 안 보낸 글을 저장하고 끝낸다 (최대 3초)
    func applicationShouldTerminate(_ s: NSApplication) -> NSApplication.TerminateReply {
        var replied = false
        let done = { if !replied { replied = true; NSApp.reply(toApplicationShouldTerminate: true) } }
        web.callAsyncJavaScript("if (typeof flush === 'function') await flush()", arguments: [:], in: nil, in: .page) { _ in done() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { done() }
        return .terminateLater
    }

    func alive(_ done: @escaping (Bool) -> Void) {
        var r = URLRequest(url: HOME_URL.appendingPathComponent("api/job"))
        r.timeoutInterval = 1
        URLSession.shared.dataTask(with: r) { _, resp, _ in
            DispatchQueue.main.async { done((resp as? HTTPURLResponse)?.statusCode == 200) }
        }.resume()
    }

    func startServer() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: PYTHONS.first { FileManager.default.isExecutableFile(atPath: $0) } ?? "/usr/bin/python3")
        p.arguments = [DIR.appendingPathComponent("server.py").path]
        p.currentDirectoryURL = DIR
        FileManager.default.createFile(atPath: "/tmp/daily-note.log", contents: nil)
        if let log = FileHandle(forWritingAtPath: "/tmp/daily-note.log") { p.standardOutput = log; p.standardError = log }
        try? p.run()                                                     // 앱을 닫아도 서버는 남는다 (명언 정리 중이면 계속)
    }

    func waitAndLoad(tries: Int) {
        alive { up in
            if up { self.web.load(URLRequest(url: HOME_URL)) }
            else if tries > 0 { DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.waitAndLoad(tries: tries - 1) } }
            else { self.web.loadHTMLString("<p style='font:16px -apple-system;padding:40px'>서버를 켜지 못했어요. /tmp/daily-note.log 를 확인해 주세요.</p>", baseURL: nil) }
        }
    }

    // obsidian:// 같은 링크는 그 앱으로 연다
    func webView(_ w: WKWebView, decidePolicyFor a: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let u = a.request.url, let s = u.scheme, s != "http", s != "https", s != "about", s != "blob", s != "data" {
            NSWorkspace.shared.open(u)
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    // 자바스크립트 alert / confirm
    func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = m; a.addButton(withTitle: "확인")
        a.beginSheetModal(for: window) { _ in completionHandler() }
    }
    func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = m; a.addButton(withTitle: "확인"); a.addButton(withTitle: "취소")
        a.beginSheetModal(for: window) { r in completionHandler(r == .alertFirstButtonReturn) }
    }

    @objc func reload() { web.reload() }

    // 메뉴가 있어야 ⌘C·⌘V·⌘Z·⌘A 가 입력 칸에서 먹는다
    func buildMenu() {
        let main = NSMenu()
        func sub(_ title: String, _ items: [NSMenuItem]) {
            let m = NSMenu(title: title); items.forEach { m.addItem($0) }
            let i = NSMenuItem(); i.submenu = m; main.addItem(i)
        }
        func item(_ t: String, _ s: Selector?, _ k: String, _ mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
            let i = NSMenuItem(title: t, action: s, keyEquivalent: k); i.keyEquivalentModifierMask = mods; return i
        }
        sub("데일리 노트", [item("데일리 노트 가리기", #selector(NSApplication.hide(_:)), "h"), .separator(),
                            item("데일리 노트 종료", #selector(NSApplication.terminate(_:)), "q")])
        sub("편집", [item("실행 취소", Selector(("undo:")), "z"), item("실행 복귀", Selector(("redo:")), "z", [.command, .shift]), .separator(),
                    item("오려두기", #selector(NSText.cut(_:)), "x"), item("복사하기", #selector(NSText.copy(_:)), "c"),
                    item("붙여넣기", #selector(NSText.paste(_:)), "v"), item("전체 선택", #selector(NSText.selectAll(_:)), "a")])
        let r = item("새로고침", #selector(reload), "r"); r.target = self
        sub("보기", [r])
        sub("윈도우", [item("최소화", #selector(NSWindow.miniaturize(_:)), "m"), item("닫기", #selector(NSWindow.performClose(_:)), "w")])
        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
