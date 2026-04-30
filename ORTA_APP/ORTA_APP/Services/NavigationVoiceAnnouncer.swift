//
//  NavigationVoiceAnnouncer.swift
//  ORTA_APP
//

import AVFoundation
import Foundation

private final class AVAudioFinishDelegate: NSObject, AVAudioPlayerDelegate {
    var onFinish: (() -> Void)?

    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        onFinish?()
        onFinish = nil
    }
}

@MainActor
final class NavigationVoiceAnnouncer: ObservableObject {
    @Published private(set) var isSpeaking = false
    /// Último fallo de síntesis (solo diagnóstico en consola en DEBUG).
    @Published private(set) var lastErrorDescription: String?

    private let client = ElevenLabsTTSClient()
    private let audioDelegate = AVAudioFinishDelegate()
    private var apiKey = ""
    private var voiceEnabled = false
    private var audioPlayer: AVAudioPlayer?

    private var speakQueue: [String] = []
    private var queueRunner: Task<Void, Never>?

    /// Evita encolar dos veces el mismo paso (p. ej. doble `onChange` en el mismo ciclo).
    private var lastQueuedManeuverFingerprint = ""
    private var lastQueuedCoachingKey = ""
    private var storedManeuverLine = ""
    private var storedCoachingLine = ""

    func configure(apiKey: String, enabled: Bool) {
        let k = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        self.apiKey = k
        voiceEnabled = enabled && !k.isEmpty
        if !voiceEnabled {
            stop()
        }
    }

    func interruptPlayback() {
        queueRunner?.cancel()
        queueRunner = nil
        audioPlayer?.stop()
        audioPlayer = nil
        speakQueue.removeAll()
        isSpeaking = false
        // Al salir del mapa, permitir volver a anunciar el mismo paso al regresar.
        lastQueuedManeuverFingerprint = ""
        lastQueuedCoachingKey = ""
    }

    func stop() {
        interruptPlayback()
        lastQueuedManeuverFingerprint = ""
        lastQueuedCoachingKey = ""
        storedManeuverLine = ""
        storedCoachingLine = ""
        lastErrorDescription = nil
    }

    func replayLast() {
        guard voiceEnabled else { return }
        queueRunner?.cancel()
        queueRunner = nil
        audioPlayer?.stop()
        audioPlayer = nil
        speakQueue.removeAll()
        if !storedManeuverLine.isEmpty { speakQueue.append(storedManeuverLine) }
        if !storedCoachingLine.isEmpty { speakQueue.append(storedCoachingLine) }
        guard !speakQueue.isEmpty else { return }
        startRunnerIfNeeded()
    }

    /// `stepFingerprint` debe incluir índice de paso + distancia + texto (p. ej. desde `DriveNavigationView`).
    func onManeuverChanged(
        stepFingerprint: String,
        distanceText: String?,
        instruction: String,
        force: Bool = false
    ) {
        guard voiceEnabled else { return }
        let ins = instruction.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !ins.isEmpty else { return }
        guard !Self.isPlaceholderInstruction(ins) else { return }
        let d = distanceText?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let line: String
        if !d.isEmpty {
            line = "\(d). \(ins)"
        } else {
            line = ins
        }
        guard !line.isEmpty else { return }
        if force {
            lastQueuedManeuverFingerprint = ""
        }
        guard stepFingerprint != lastQueuedManeuverFingerprint else { return }
        lastQueuedManeuverFingerprint = stepFingerprint
        storedManeuverLine = line
        enqueue(line)
    }

    func onCoachingSegmentChanged(_ segment: CoachingSegment?, force: Bool = false) {
        guard voiceEnabled, let segment else { return }
        let brief = segment.speechBriefForVoice
        guard !brief.isEmpty else { return }
        let key = "\(segment.segIdx)|\(brief)"
        if force {
            lastQueuedCoachingKey = ""
        }
        guard key != lastQueuedCoachingKey else { return }
        lastQueuedCoachingKey = key
        let line = "Consejo ORTA. \(brief)"
        storedCoachingLine = line
        enqueue(line)
    }

    private static func isPlaceholderInstruction(_ ins: String) -> Bool {
        let t = ins.folding(options: .diacriticInsensitive, locale: .current).lowercased()
        return t.hasPrefix("calculando maniobra")
    }

    private func enqueue(_ line: String) {
        let t = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        speakQueue.append(t)
        startRunnerIfNeeded()
    }

    private func startRunnerIfNeeded() {
        guard queueRunner == nil else { return }
        queueRunner = Task { @MainActor in
            await self.runQueue()
            self.queueRunner = nil
            if !self.speakQueue.isEmpty {
                self.startRunnerIfNeeded()
            }
        }
    }

    private func runQueue() async {
        while !speakQueue.isEmpty {
            if Task.isCancelled {
                speakQueue.removeAll()
                return
            }
            let line = speakQueue.removeFirst()
            await speakOne(line)
        }
    }

    private func speakOne(_ line: String) async {
        isSpeaking = true
        defer { isSpeaking = false }
        do {
            let data = try await client.synthesize(text: line, apiKey: apiKey)
            try? AVAudioSession.sharedInstance().setCategory(
                .playback,
                mode: .spokenAudio,
                options: [.duckOthers, .defaultToSpeaker]
            )
            try? AVAudioSession.sharedInstance().setActive(true)
            await MainActor.run { lastErrorDescription = nil }
            await playMPEGData(data)
        } catch {
            let msg: String
            if let le = error as? LocalizedError, let d = le.errorDescription {
                msg = d
            } else {
                msg = (error as NSError).localizedDescription
            }
            await MainActor.run { lastErrorDescription = msg }
            #if DEBUG
            print("[ORTA voice] synthesize/play error: \(error)")
            #endif
        }
    }

    private func playMPEGData(_ data: Data) async {
        await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
            do {
                let player = try AVAudioPlayer(data: data)
                self.audioPlayer?.stop()
                self.audioPlayer = player
                self.audioDelegate.onFinish = {
                    cont.resume()
                }
                player.delegate = self.audioDelegate
                player.prepareToPlay()
                guard player.play() else {
                    cont.resume()
                    return
                }
            } catch {
                cont.resume()
            }
        }
    }
}
