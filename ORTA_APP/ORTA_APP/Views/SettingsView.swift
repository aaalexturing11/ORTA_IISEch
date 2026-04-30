//
//  SettingsView.swift
//  ORTA_APP
//

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var session: AppSession
    @State private var urlDraft: String = ""
    @State private var priceDraft: String = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("URL base (sin barra final)", text: $urlDraft)
                        .textContentType(.URL)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                    Text("Simulador iOS → Mac: `http://127.0.0.1:8000` con el dashboard FastAPI en marcha.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } header: {
                    Text("Servidor ORTA")
                }

                Section {
                    TextField("Precio diesel (MXN/L)", text: $priceDraft)
                        .keyboardType(.decimalPad)
                } header: {
                    Text("Economía")
                }

                Section {
                    Button("Guardar") {
                        session.apiBaseURL = urlDraft.trimmingCharacters(in: .whitespacesAndNewlines)
                        if let p = Double(priceDraft.replacingOccurrences(of: ",", with: ".")) {
                            session.dieselPriceMXNPerL = p
                        }
                    }
                }
            }
            .navigationTitle("Ajustes")
            .onAppear {
                urlDraft = session.apiBaseURL
                priceDraft = String(format: "%.2f", session.dieselPriceMXNPerL)
            }
        }
    }
}

#Preview {
    SettingsView()
        .environmentObject(AppSession())
}
