//
//  AppSession.swift
//  ORTA_APP
//

import Foundation
import Combine

final class AppSession: ObservableObject {
    @Published var apiBaseURL: String {
        didSet { UserDefaults.standard.set(apiBaseURL, forKey: Self.baseURLKey) }
    }
    @Published var selectedRouteSlug: String?
    @Published var selectedTruckSlug: String?
    @Published var dieselPriceMXNPerL: Double {
        didSet { UserDefaults.standard.set(dieselPriceMXNPerL, forKey: Self.priceKey) }
    }

    private static let baseURLKey = "orta.apiBaseURL"
    private static let priceKey = "orta.dieselPriceMXNPerL"

    init() {
        let d = UserDefaults.standard
        apiBaseURL = d.string(forKey: Self.baseURLKey) ?? "http://127.0.0.1:8000"
        dieselPriceMXNPerL = d.object(forKey: Self.priceKey) as? Double ?? 24.5
    }

    var hasSelection: Bool {
        selectedRouteSlug != nil && selectedTruckSlug != nil
    }
}
