#!/usr/bin/env swift

// PicNote Vision OCR CLI Helper
// Uses Apple Vision framework for text recognition and barcode/QR detection.
// Outputs JSON to stdout.
//
// Usage: vision_ocr <image_path>
// Output: {"text": "...", "qr_codes": ["..."], "text_blocks": [...]}

import Foundation
import Vision
import AppKit

struct TextBlock: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct VisionResult: Codable {
    let text: String
    let textBlocks: [TextBlock]
    let qrCodes: [String]
    let barcodes: [String]

    enum CodingKeys: String, CodingKey {
        case text
        case textBlocks = "text_blocks"
        case qrCodes = "qr_codes"
        case barcodes
    }
}

func processImage(at path: String) -> VisionResult? {
    guard let image = NSImage(contentsOfFile: path) else {
        fputs("Error: Cannot load image at \(path)\n", stderr)
        return nil
    }

    guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        fputs("Error: Cannot create CGImage from \(path)\n", stderr)
        return nil
    }

    var allText = ""
    var textBlocks: [TextBlock] = []
    var qrCodes: [String] = []
    var barcodes: [String] = []

    // Text Recognition Request
    let textRequest = VNRecognizeTextRequest { request, error in
        if let error = error {
            fputs("OCR Error: \(error.localizedDescription)\n", stderr)
            return
        }

        guard let observations = request.results as? [VNRecognizedTextObservation] else { return }

        var lines: [String] = []
        for observation in observations {
            guard let topCandidate = observation.topCandidates(1).first else { continue }

            lines.append(topCandidate.string)

            let bbox = observation.boundingBox
            let block = TextBlock(
                text: topCandidate.string,
                confidence: topCandidate.confidence,
                x: bbox.origin.x,
                y: bbox.origin.y,
                width: bbox.width,
                height: bbox.height
            )
            textBlocks.append(block)
        }
        allText = lines.joined(separator: "\n")
    }

    // Configure for best accuracy, support multiple languages
    textRequest.recognitionLevel = .accurate
    textRequest.recognitionLanguages = ["en-US", "zh-Hans", "zh-Hant", "ja", "ko"]
    textRequest.usesLanguageCorrection = true

    // Barcode Detection Request (includes QR codes)
    let barcodeRequest = VNDetectBarcodesRequest { request, error in
        if let error = error {
            fputs("Barcode Error: \(error.localizedDescription)\n", stderr)
            return
        }

        guard let observations = request.results as? [VNBarcodeObservation] else { return }

        for observation in observations {
            guard let payload = observation.payloadStringValue else { continue }

            if observation.symbology == .qr {
                qrCodes.append(payload)
            } else {
                barcodes.append(payload)
            }
        }
    }

    // Run both requests
    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([textRequest, barcodeRequest])
    } catch {
        fputs("Vision Error: \(error.localizedDescription)\n", stderr)
        return nil
    }

    return VisionResult(
        text: allText,
        textBlocks: textBlocks,
        qrCodes: qrCodes,
        barcodes: barcodes
    )
}

// Main
guard CommandLine.arguments.count > 1 else {
    fputs("Usage: vision_ocr <image_path>\n", stderr)
    exit(1)
}

let imagePath = CommandLine.arguments[1]

guard FileManager.default.fileExists(atPath: imagePath) else {
    fputs("Error: File not found: \(imagePath)\n", stderr)
    exit(1)
}

if let result = processImage(at: imagePath) {
    let encoder = JSONEncoder()
    encoder.outputFormatting = .prettyPrinted
    if let data = try? encoder.encode(result) {
        print(String(data: data, encoding: .utf8) ?? "{}")
    }
} else {
    // Return empty result on failure rather than crashing
    print("{\"text\": \"\", \"text_blocks\": [], \"qr_codes\": [], \"barcodes\": []}")
    exit(1)
}
