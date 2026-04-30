//
//  ORTAAPIService.swift
//  ORTA_APP
//

import Foundation

enum ORTAAPIError: LocalizedError {
    case invalidURL
    case status(Int)
    case decode(Error)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "URL del servidor inválida."
        case .status(let c): return "El servidor respondió \(c)."
        case .decode(let e): return "No se pudo leer la respuesta: \(e.localizedDescription)"
        }
    }
}

struct ORTAAPIService: Sendable {
    let baseURL: String

    private func url(_ path: String, query: [String: String] = [:]) throws -> URL {
        let trimmed = baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        var c = URLComponents(string: "\(trimmed)\(path)")
        if !query.isEmpty {
            c?.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        }
        guard let u = c?.url else { throw ORTAAPIError.invalidURL }
        return u
    }

    private func get<T: Decodable>(_ path: String, query: [String: String] = [:]) async throws -> T {
        let u = try url(path, query: query)
        var req = URLRequest(url: u)
        req.httpMethod = "GET"
        req.timeoutInterval = 30
        let (data, res) = try await URLSession.shared.data(for: req)
        let code = (res as? HTTPURLResponse)?.statusCode ?? 0
        guard (200 ... 299).contains(code) else { throw ORTAAPIError.status(code) }
        do {
            let dec = JSONDecoder()
            return try dec.decode(T.self, from: data)
        } catch {
            throw ORTAAPIError.decode(error)
        }
    }

    func fetchRoutes() async throws -> [ORTARouteSummary] {
        let r: RoutesResponse = try await get("/api/routes")
        return r.routes
    }

    func fetchKPIs(route: String, truck: String, since: String? = nil) async throws -> KPIsResponse {
        var q = ["route": route, "truck": truck]
        if let s = since, !s.isEmpty { q["since"] = s }
        return try await get("/api/kpis", query: q)
    }

    func fetchCoaching(route: String, truck: String, since: String? = nil) async throws -> CoachingResponse {
        var q = ["route": route, "truck": truck]
        if let s = since, !s.isEmpty { q["since"] = s }
        return try await get("/api/route/coaching", query: q)
    }
}
