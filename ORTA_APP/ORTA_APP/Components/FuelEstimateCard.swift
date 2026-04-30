//
//  FuelEstimateCard.swift
//  ORTA_APP
//

import SwiftUI

struct FuelEstimateCard: View {
    let routeLabel: String
    let distanceKm: Double?
    let fuelLPer100km: Double?
    let dieselPriceMXNPerL: Double
    let nTripsSample: Int?

    private var litersEstimate: Double? {
        guard let d = distanceKm, d > 0, let f = fuelLPer100km, f > 0 else { return nil }
        return d * f / 100.0
    }

    private var costMXN: Double? {
        guard let l = litersEstimate else { return nil }
        return l * dieselPriceMXNPerL
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Estimación de combustible", systemImage: "fuelpump.fill")
                .font(.headline)
                .foregroundStyle(ORTATheme.accent)

            Text(routeLabel)
                .font(.subheadline)
                .foregroundStyle(.secondary)

            if let d = distanceKm {
                HStack {
                    metric(title: "Distancia", value: String(format: "%.0f km", d))
                    if let l = litersEstimate {
                        metric(title: "Diesel (aprox.)", value: String(format: "%.0f L", l))
                    }
                    if let c = costMXN {
                        metric(title: "Costo (aprox.)", value: String(format: "$%.0f MXN", c))
                    }
                }
            }

            if let f = fuelLPer100km {
                Text("Basado en \(String(format: "%.1f", f)) L/100 km del histórico de simulaciones para esta ruta y camión.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if let n = nTripsSample, n > 0 {
                Text("Muestra: \(n) viaje(s) en el filtro actual.")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(ORTATheme.card)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(Color.white.opacity(0.06), lineWidth: 1)
        )
    }

    private func metric(title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.subheadline)
                .fontWeight(.semibold)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

#Preview {
    FuelEstimateCard(
        routeLabel: "Puebla → Cuautitlán",
        distanceKm: 210,
        fuelLPer100km: 32.5,
        dieselPriceMXNPerL: 24.5,
        nTripsSample: 12
    )
    .padding()
    .background(ORTATheme.bg)
}
