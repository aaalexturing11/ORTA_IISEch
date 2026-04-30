//
//  LegalDisclaimerBanner.swift
//  ORTA_APP
//

import SwiftUI

struct LegalDisclaimerBanner: View {
    var body: some View {
        Text("Los avisos son asesoría para ahorrar combustible. Respeta límites de velocidad y señalización.")
            .font(.caption2)
            .foregroundStyle(ORTATheme.textSecondary)
            .multilineTextAlignment(.center)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity)
            .background(ORTATheme.card.opacity(0.9))
    }
}

#Preview {
    LegalDisclaimerBanner()
}
