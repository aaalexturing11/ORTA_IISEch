//
//  ElevenLabsTTSClient.swift
//  ORTA_APP
//

import Foundation

/// Cliente mínimo para `POST /v1/text-to-speech/{voice_id}` (audio/mpeg).
struct ElevenLabsTTSClient: Sendable {
    /// Voz configurada para anuncios de navegación y ORTA.
    static let ortaNavigationVoiceId = "OYTbf65OHHFELVut7v2H"

    enum ClientError: Error, LocalizedError {
        case invalidURL
        case badStatus(Int, String?)
        case emptyBody

        var errorDescription: String? {
            switch self {
            case .invalidURL: return "URL ElevenLabs inválida."
            case .badStatus(let code, let detail):
                if let d = detail, !d.isEmpty { return "ElevenLabs HTTP \(code): \(d)" }
                return "ElevenLabs rechazó la petición (HTTP \(code))."
            case .emptyBody: return "ElevenLabs devolvió audio vacío."
            }
        }
    }

    private struct RequestBody: Encodable {
        let text: String
        let model_id: String
    }

    private static let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.timeoutIntervalForRequest = 45
        c.timeoutIntervalForResource = 60
        return URLSession(configuration: c)
    }()

    func synthesize(
        text: String,
        apiKey: String,
        voiceId: String = Self.ortaNavigationVoiceId
    ) async throws -> Data {
        let cleaned = text
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { throw ClientError.emptyBody }
        guard let url = URL(string: "https://api.elevenlabs.io/v1/text-to-speech/\(voiceId)") else {
            throw ClientError.invalidURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue(apiKey, forHTTPHeaderField: "xi-api-key")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("audio/mpeg", forHTTPHeaderField: "Accept")
        let body = RequestBody(text: cleaned, model_id: "eleven_multilingual_v2")
        req.httpBody = try JSONEncoder().encode(body)
        let (data, resp) = try await Self.session.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw ClientError.badStatus(-1, nil) }
        guard (200 ... 299).contains(http.statusCode) else {
            let snippet: String?
            if let s = String(data: data, encoding: .utf8) {
                let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
                snippet = t.count > 220 ? String(t.prefix(220)) + "…" : t
            } else {
                snippet = nil
            }
            throw ClientError.badStatus(http.statusCode, snippet)
        }
        guard !data.isEmpty else { throw ClientError.emptyBody }
        return data
    }
}
