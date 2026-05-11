//
//  SettingsView.swift
//  ORTA_APP
//

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var session: AppSession
    @State private var urlDraft: String = ""
    @State private var priceDraft: String = ""
    @State private var elevenLabsKeyDraft: String = ""
    @State private var voiceGuidanceDraft: Bool = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle("Anuncios de voz (maniobra + ORTA)", isOn: $voiceGuidanceDraft)
                    SecureField("Clave en Ajustes (opcional, sobrescribe la del código)", text: $elevenLabsKeyDraft)
                        .textContentType(.password)
                        .autocorrectionDisabled()
                    Text(
                        "Si definís clave en `ORTASecrets.elevenLabsApiKeyEmbedded`, esa tiene prioridad sobre el campo de abajo. " +
                            "No subas claves reales a repos públicos."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                } header: {
                    Text("Voz (ElevenLabs)")
                }

                Section {
                    TextField("URL base (sin barra final)", text: $urlDraft)
                        .textContentType(.URL)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                    Text(
                        "Simulador: http://127.0.0.1:8000. iPhone físico: esa URL apunta al teléfono. " +
                            "Usá la IP LAN de tu Mac (misma Wi‑Fi), p. ej. http://192.168.1.42:8000, con uvicorn en la Mac: --host 0.0.0.0 --port 8000. " +
                            "Alternativa: túnel (cloudflared tunnel --url http://127.0.0.1:8000 o ngrok) y pegás la URL https."
                    )
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
                        session.voiceGuidanceEnabled = voiceGuidanceDraft
                        session.elevenLabsApiKey = elevenLabsKeyDraft.trimmingCharacters(in: .whitespacesAndNewlines)
                    }
                }
            }
            .navigationTitle("Ajustes")
            .onAppear {
                urlDraft = session.apiBaseURL
                priceDraft = String(format: "%.2f", session.dieselPriceMXNPerL)
                voiceGuidanceDraft = session.voiceGuidanceEnabled
                elevenLabsKeyDraft = session.elevenLabsApiKey
            }
        }
    }
}

#Preview {
    SettingsView()
        .environmentObject(AppSession())
}
