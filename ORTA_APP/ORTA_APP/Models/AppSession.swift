//
//  AppSession.swift
//  ORTA_APP
//

import Foundation
import Combine

final class AppSession: ObservableObject {
    /// 0 = planear viaje, 1 = mapa, 2 = ajustes (orden del `TabView` en `ContentView`).
    @Published var selectedMainTabIndex: Int = 0
    @Published var apiBaseURL: String {
        didSet { UserDefaults.standard.set(apiBaseURL, forKey: Self.baseURLKey) }
    }
    @Published var selectedRouteSlug: String?
    @Published var selectedTruckSlug: String?
    @Published var dieselPriceMXNPerL: Double {
        didSet { UserDefaults.standard.set(dieselPriceMXNPerL, forKey: Self.priceKey) }
    }

    /// Anuncios por voz (maniobra MapKit + consejo ORTA vía ElevenLabs).
    @Published var voiceGuidanceEnabled: Bool = false {
        didSet { UserDefaults.standard.set(voiceGuidanceEnabled, forKey: Self.voiceGuidanceKey) }
    }

    /// API key `xi-api-key` opcional en Ajustes (sobrescribe la de `ORTASecrets` si no está vacía).
    @Published var elevenLabsApiKey: String = "" {
        didSet { UserDefaults.standard.set(elevenLabsApiKey, forKey: Self.elevenLabsKey) }
    }

    private static let baseURLKey = "orta.apiBaseURL"
    private static let priceKey = "orta.dieselPriceMXNPerL"
    private static let voiceGuidanceKey = "orta.voiceGuidanceEnabled"
    private static let elevenLabsKey = "orta.elevenLabsApiKey"

    init() {
        let d = UserDefaults.standard
        apiBaseURL = d.string(forKey: Self.baseURLKey) ?? "http://127.0.0.1:8000"
        dieselPriceMXNPerL = d.object(forKey: Self.priceKey) as? Double ?? 24.5
        voiceGuidanceEnabled = d.bool(forKey: Self.voiceGuidanceKey)
        elevenLabsApiKey = d.string(forKey: Self.elevenLabsKey) ?? ""
    }

    /// Key efectiva: si hay clave en `ORTASecrets`, esa (prioridad); si no, la de Ajustes.
    var resolvedElevenLabsApiKey: String {
        let embedded = ORTASecrets.elevenLabsApiKeyEmbedded.trimmingCharacters(in: .whitespacesAndNewlines)
        if !embedded.isEmpty { return embedded }
        return elevenLabsApiKey.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var hasElevenLabsApiKey: Bool {
        !resolvedElevenLabsApiKey.isEmpty
    }

    var hasSelection: Bool {
        selectedRouteSlug != nil && selectedTruckSlug != nil
    }
}
