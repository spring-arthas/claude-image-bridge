import AppKit
import Foundation
import ImageIO

struct ClipboardEntry: Codable {
    let kind: String
    let path: String
    let uti: String?
}

struct ClipboardPayload: Codable {
    let items: [ClipboardEntry]
}

func tempFilePath(for suffix: String, prefix: String) -> URL {
    let dir = URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
        .appendingPathComponent("claude-image-bridge", isDirectory: true)
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let filename = "\(prefix)-\(UUID().uuidString.prefix(8)).\(suffix)"
    return dir.appendingPathComponent(filename)
}

func writeData(_ data: Data, suffix: String, prefix: String) throws -> String {
    let url = tempFilePath(for: suffix, prefix: prefix)
    try data.write(to: url, options: .atomic)
    return url.path
}

func isLikelyFilePath(_ value: String) -> Bool {
    let expanded = (value as NSString).expandingTildeInPath
    return FileManager.default.fileExists(atPath: expanded)
}

func clipboardItems() -> [ClipboardEntry] {
    let pasteboard = NSPasteboard.general
    var entries: [ClipboardEntry] = []

    if let items = pasteboard.pasteboardItems {
        for item in items {
            if let fileURLString = item.string(forType: .fileURL),
               let url = URL(string: fileURLString),
               url.isFileURL {
                entries.append(ClipboardEntry(kind: "file", path: url.path, uti: "public.file-url"))
                continue
            }

            let preferredTypes: [NSPasteboard.PasteboardType] = [
                .png,
                .tiff,
                .pdf,
                .fileURL,
                .string,
            ]

            for type in preferredTypes {
                if type == .string, let text = item.string(forType: .string) {
                    if isLikelyFilePath(text) {
                        entries.append(ClipboardEntry(kind: "text", path: (text as NSString).expandingTildeInPath, uti: "public.utf8-plain-text"))
                        break
                    }
                    continue
                }

                guard let data = item.data(forType: type) else { continue }

                do {
                    if type == .png {
                        let path = try writeData(data, suffix: "png", prefix: "clipboard")
                        entries.append(ClipboardEntry(kind: "image", path: path, uti: "public.png"))
                        break
                    } else if type == .tiff {
                        let path = try writeData(data, suffix: "tiff", prefix: "clipboard")
                        entries.append(ClipboardEntry(kind: "image", path: path, uti: "public.tiff"))
                        break
                    } else if type == .pdf {
                        let path = try writeData(data, suffix: "pdf", prefix: "clipboard")
                        entries.append(ClipboardEntry(kind: "pdf", path: path, uti: "com.adobe.pdf"))
                        break
                    } else if type == .fileURL {
                        if let url = URL(dataRepresentation: data, relativeTo: nil), url.isFileURL {
                            entries.append(ClipboardEntry(kind: "file", path: url.path, uti: "public.file-url"))
                            break
                        }
                    }
                } catch {
                    continue
                }
            }
        }
    }

    if entries.isEmpty, let objects = pasteboard.readObjects(forClasses: [NSImage.self], options: nil) as? [NSImage] {
        for image in objects {
            guard let tiff = image.tiffRepresentation,
                  let rep = NSBitmapImageRep(data: tiff),
                  let pngData = rep.representation(using: .png, properties: [:]) else {
                continue
            }
            if let path = try? writeData(pngData, suffix: "png", prefix: "clipboard") {
                entries.append(ClipboardEntry(kind: "image", path: path, uti: "public.png"))
            }
        }
    }

    return entries
}

let payload = ClipboardPayload(items: clipboardItems())
let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
if let data = try? encoder.encode(payload) {
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} else {
    FileHandle.standardError.write(Data("failed to encode clipboard payload\n".utf8))
    exit(1)
}
