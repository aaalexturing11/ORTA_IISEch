//
//  TurnStepsStrip.swift
//  ORTA_APP
//

import SwiftUI

/// Maniobras resumidas desde MapKit (giros); no sustituyen señalización real.
struct TurnStepsStrip: View {
    let steps: [String]
    let maxVisible: Int

    init(steps: [String], maxVisible: Int = 4) {
        self.steps = steps
        self.maxVisible = maxVisible
    }

    var body: some View {
        Group {
            if steps.isEmpty {
                Text("Calculando indicaciones…")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    Label("Indicaciones (MapKit)", systemImage: "arrow.turn.up.right")
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundStyle(ORTATheme.accent)
                    ForEach(Array(steps.prefix(maxVisible).enumerated()), id: \.offset) { _, line in
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "chevron.forward")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                            Text(line)
                                .font(.caption)
                                .foregroundStyle(.primary)
                        }
                    }
                    if steps.count > maxVisible {
                        Text("+\(steps.count - maxVisible) más…")
                            .font(.caption2)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

#Preview {
    TurnStepsStrip(steps: ["Gira a la derecha en Av. Principal", "Continúa 2 km"])
        .padding()
        .background(ORTATheme.card)
}
