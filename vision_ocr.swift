import Foundation
import CoreGraphics
import ImageIO
import Vision

struct OCRLine: Codable {
    struct Box: Codable {
        let x: Double
        let y: Double
        let width: Double
        let height: Double
    }

    let text: String
    let confidence: Double
    let boundingBox: Box
}

struct OCRResult: Codable {
    let imagePath: String
    let text: String
    let lines: [OCRLine]
    let language: String
}

func recognizeText(at path: String) throws -> OCRResult {
    let url = URL(fileURLWithPath: path)
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.usesCPUOnly = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]

    let handler = VNImageRequestHandler(url: url, options: [:])
    try handler.perform([request])

    let observations = request.results ?? []
    var lines: [OCRLine] = []
    for observation in observations {
        guard let best = observation.topCandidates(1).first else { continue }
        let box = observation.boundingBox
        lines.append(
            OCRLine(
                text: best.string,
                confidence: Double(best.confidence),
                boundingBox: OCRLine.Box(
                    x: Double(box.origin.x),
                    y: Double(box.origin.y),
                    width: Double(box.size.width),
                    height: Double(box.size.height)
                )
            )
        )
    }

    let text = lines.map { $0.text }.joined(separator: "\n")
    return OCRResult(imagePath: path, text: text, lines: lines, language: "zh-Hans,en-US")
}

do {
    guard CommandLine.arguments.count >= 2 else {
        throw NSError(domain: "ImageBridge", code: 3, userInfo: [NSLocalizedDescriptionKey: "missing image path"])
    }
    let result = try recognizeText(at: CommandLine.arguments[1])
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    let data = try encoder.encode(result)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    let ns = error as NSError
    let details = [
        "OCR error: \(ns.localizedDescription)",
        "domain=\(ns.domain)",
        "code=\(ns.code)",
        "info=\(ns.userInfo)",
    ].joined(separator: "\n")
    FileHandle.standardError.write(Data((details + "\n").utf8))
    exit(1)
}
