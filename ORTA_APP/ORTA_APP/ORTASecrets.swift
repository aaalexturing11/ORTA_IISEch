//
//  ORTASecrets.swift
//  ORTA_APP
//
//  Claves incrustadas para desarrollo. No subas este archivo a repositorios públicos
//  si pegas una API key real (usa un repo privado o borra la clave antes de publicar).
//

import Foundation

enum ORTASecrets {
    /// Pega aquí tu `xi-api-key` de ElevenLabs. Si no está vacía, la app la usa sin tener que cargarla en Ajustes.
    /// Ajustes siguen pudiendo sobrescribirla si escribes otra clave ahí.
    static let elevenLabsApiKeyEmbedded: String = "sk_96ca716d4fc74896ab6e5b469f9ae30f40d7d8aebcb271d2"
}
