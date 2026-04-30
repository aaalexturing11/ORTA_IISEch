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

private final class SystemSpeechDelegate: NSObject, AVSpeechSynthesizerDelegate {
    var onFinish: (() -> Void)?

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        onFinish?()
        onFinish = nil
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        onFinish?()
        onFinish = nil
    }
}

@MainActor
final class NavigationVoiceAnnouncer: ObservableObject {
    @Published private(set) var isSpeaking = false
    @Published private(set) var lastErrorDescription: String?

    private let client = ElevenLabsTTSClient()
    private let audioDelegate = AVAudioFinishDelegate()
    private let systemSynth = AVSpeechSynthesizer()
    private let systemSpeechDelegate = SystemSpeechDelegate()

    private var apiKey = ""
    /// Anuncios activados (Ajustes), con o sin clave ElevenLabs.
    private var voiceEnabled = false

    private var audioPlayer: AVAudioPlayer?

    private var speakQueue: [String] = []
    private var queueRunner: Task<Void, Never>?

    private var lastQueuedManeuverFingerprint = ""
    private var lastQueuedCoachingKey = ""
    private var storedManeuverLine = ""
    private var storedCoachingLine = ""

    func configure(apiKey: String, enabled: Bool) {
        let k = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        self.apiKey = k
        voiceEnabled = enabled
        if !enabled {
            stop()
        }
    }

    /// `true` si hay clave para intentar ElevenLabs antes que la voz del sistema.
    private var canUseElevenLabs: Bool {
        !apiKey.isEmpty
    }

    func interruptPlayback() {
        queueRunner?.cancel()
        queueRunner = nil
        audioPlayer?.stop()
        audioPlayer = nil
        if systemSynth.isSpeaking {
            systemSynth.stopSpeaking(at: .immediate)
        }
        speakQueue.removeAll()
        isSpeaking = false
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
        if systemSynth.isSpeaking {
            systemSynth.stopSpeaking(at: .immediate)
        }
        speakQueue.removeAll()
        if !storedManeuverLine.isEmpty { speakQueue.append(storedManeuverLine) }
        if !storedCoachingLine.isEmpty { speakQueue.append(storedCoachingLine) }
        guard !speakQueue.isEmpty else { return }
        startRunnerIfNeeded()
    }

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

    private func activatePlaybackSession() {
        try? AVAudioSession.sharedInstance().setCategory(
            .playback,
            mode: .spokenAudio,
            options: [.duckOthers, .defaultToSpeaker]
        )
        try? AVAudioSession.sharedInstance().setActive(true)
    }

    private func speakOne(_ line: String) async {
        isSpeaking = true
        defer { isSpeaking = false }
        activatePlaybackSession()

        if !canUseElevenLabs {
            await MainActor.run {
                lastErrorDescription = nil
            }
            await speakSystemLine(line)
            return
        }

        do {
            let data = try await client.synthesize(text: line, apiKey: apiKey)
            await MainActor.run { lastErrorDescription = nil }
            let played = await playMPEGData(data)
            if !played {
                await MainActor.run {
                    lastErrorDescription = "No se pudo reproducir el audio de ElevenLabs; usando voz del sistema."
                }
                await speakSystemLine(line)
            }
        } catch {
            let msg: String
            if let le = error as? LocalizedError, let d = le.errorDescription {
                msg = d
            } else {
                msg = (error as NSError).localizedDescription
            }
            await MainActor.run {
                lastErrorDescription = "\(msg) · Se usa voz del sistema."
            }
            #if DEBUG
            print("[ORTA voice] ElevenLabs error: \(error)")
            #endif
            await speakSystemLine(line)
        }
    }

    /// - Returns: `true` si se oyó audio hasta el final del clip.
    private func playMPEGData(_ data: Data) async -> Bool {
        await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            do {
                let player = try AVAudioPlayer(data: data)
                self.audioPlayer?.stop()
                self.audioPlayer = player
                self.audioDelegate.onFinish = {
                    cont.resume(returning: true)
                }
                player.delegate = self.audioDelegate
                player.prepareToPlay()
                guard player.play() else {
                    cont.resume(returning: false)
                    return
                }
            } catch {
                cont.resume(returning: false)
            }
        }
    }

    private func speakSystemLine(_ line: String) async {
        await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
            activatePlaybackSession()
            systemSpeechDelegate.onFinish = {
                cont.resume(returning: ())
            }
            systemSynth.delegate = systemSpeechDelegate
            if systemSynth.isSpeaking {
                systemSynth.stopSpeaking(at: .immediate)
            }
            let u = AVSpeechUtterance(string: line)
            u.voice =
                AVSpeechSynthesisVoice(language: "es-MX")
                ?? AVSpeechSynthesisVoice(language: "es-419")
                ?? AVSpeechSynthesisVoice(language: "es-ES")
            u.rate = 0.48
            u.volume = 1.0
            systemSynth.speak(u)
        }
    }
}
