import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Animated, AppState, Dimensions, Easing, FlatList, I18nManager, Keyboard, KeyboardAvoidingView, Linking,
  Modal, Platform, Pressable, ScrollView, Share, StyleSheet, Text, TextInput, View, useColorScheme,
} from "react-native";
import { AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder } from "expo-audio";
import { File, Paths } from "expo-file-system";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { SafeAreaProvider, SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import * as SecureStore from "expo-secure-store";

// Módulos nativos opcionais: num APK antigo, a função some sem travar o app.
const opt = (load: () => any) => { try { return load(); } catch { return null; } };
const Notifications: any = opt(() => require("expo-notifications"));
const KeepAwake: any = opt(() => require("expo-keep-awake"));
const Speech: any = opt(() => require("expo-speech"));  // voz do Fidus no modo conversa (APK com expo-speech)
const DocumentPicker: any = opt(() => require("expo-document-picker"));
const Clipboard: any = opt(() => require("expo-clipboard"));  // botão copiar (sem ele, abre o compartilhar)
// Assinatura pela Google Play / App Store (RevenueCat). Só funciona no APK com o módulo e com as chaves no servidor.
// só usa se o módulo nativo existir no APK (num APK antigo a biblioteca entraria em "modo de demonstração")
const hasNativePurchases = !!opt(() => {
  const RN = require("react-native");
  return RN.NativeModules?.RNPurchases || RN.TurboModuleRegistry?.get?.("RNPurchases");
});
const PurchasesMod: any = hasNativePurchases ? opt(() => require("react-native-purchases")) : null;
const Purchases: any = PurchasesMod ? (PurchasesMod.default || PurchasesMod) : null;
// trava com digital/rosto (APK com expo-local-authentication)
const LocalAuth: any = opt(() => require("expo-local-authentication"));
// transcrição no próprio celular enquanto a pessoa fala (APK com expo-speech-recognition): bem mais rápido
const SpeechRec: any = opt(() => require("expo-speech-recognition").ExpoSpeechRecognitionModule);
// tocar a voz natural (MP3 que vem do servidor)
const createPlayer: any = opt(() => require("expo-audio").createAudioPlayer);
// o que este app tem (o servidor guarda para o painel e para o suporte saber se o APK está certo)
const UPDATE_ID: string = String(opt(() => require("expo-updates").updateId) || "apk");
const CLIENT_CAPS = `sr=${SpeechRec ? 1 : 0},speech=${opt(() => require("expo-speech")) ? 1 : 0},player=${createPlayer ? 1 : 0},js=0.9.8,ota=${UPDATE_ID.slice(0, 8)}`;
const MANAGE_SUBS_URL = Platform.OS === "ios" ? "https://apps.apple.com/account/subscriptions"
  : "https://play.google.com/store/account/subscriptions";

// ---------- Idiomas ----------
// O app é escrito em português. Em outro idioma, o servidor devolve as traduções (feitas uma vez e guardadas),
// e o app guarda uma cópia no celular para abrir já traduzido.
let LANG = "pt";
let LOCALE = "pt-BR";
let TR: Record<string, string> = {};
function t(s: string, ...a: any[]): string {
  let x = TR[s] ?? s;
  a.forEach((v, i) => { x = x.split(`{${i}}`).join(String(v)); });
  return x;
}
function deviceLocale(): string {
  const clean = (id: string) => {
    const p = String(id).split(/[_-]/);
    return p[1] && /^[A-Za-z]{2}$/.test(p[1]) ? `${p[0].toLowerCase()}-${p[1].toUpperCase()}` : p[0].toLowerCase();
  };
  try { const id = (I18nManager as any).getConstants?.().localeIdentifier; if (id) return clean(id); } catch {}
  try { const l = Intl.DateTimeFormat().resolvedOptions().locale; if (l) return clean(l); } catch {}
  return "en";
}
function deviceTimezone(): string | null {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || null; } catch { return null; }
}
const LANG_CHOICES: [string, string][] = [
  ["pt", "Português"], ["en", "English"], ["es", "Español"], ["fr", "Français"], ["de", "Deutsch"], ["it", "Italiano"],
  ["nl", "Nederlands"], ["pl", "Polski"], ["ro", "Română"], ["ms", "Bahasa Melayu"], ["id", "Bahasa Indonesia"],
  ["tr", "Türkçe"], ["ar", "العربية"], ["hi", "हिन्दी"], ["zh", "中文"], ["ja", "日本語"],
];
const TTS_LOCALE: Record<string, string> = { pt: "pt-BR", en: "en-GB", es: "es-ES", fr: "fr-FR", de: "de-DE", it: "it-IT" };
// textos que vêm do servidor em português (planos): listados aqui para entrarem na tradução
const _SERVER_TEXTS = () => [
  t("Voz e texto sem limite"), t("Agenda, lembretes e bom dia"), t("E-mail com aprovação"), t("Gastos e recibos de 1 carteira"),
  t("Documentos com validade"), t("Tarefas"), t("Empresas e moedas ilimitadas"), t("Link de agendamento para clientes"),
  t("Ata de reunião automática"), t("Pacote do contador"), t("Alerta de assinaturas"), t("Resumo da semana"),
  t("Banco conectado: gastos entram sozinhos"), t("Cobrança e fatura para clientes"), t("Mais 1 pessoa na conta + acesso do contador"),
  t("Atas sem limite e suporte prioritário"), t("link de agendamento"), t("atas de reunião"), t("gravar reuniões e gerar a ata"),
  t("pacote do contador"), t("alerta de assinaturas"), t("resumo da semana"), t("gastos de mais de uma empresa"),
  t("banco conectado"), t("cobrança e fatura para clientes"), t("mais uma pessoa na conta"), t("Negócio"),
  t("Essencial"), t("Premium"), t("combustível"), t("alimentação"), t("transporte"), t("materiais"), t("ferramentas"),
  t("manutenção"), t("escritório"), t("software"), t("telefone e internet"), t("impostos e taxas"), t("moradia"), t("saúde"),
  t("lazer"), t("viagem"), t("salários e prestadores"), t("outros"),
  t("código expirado. Peça um novo."), t("código errado."), t("este e-mail não tem acesso ao Fidus."),
  t("esta conta entra com o Google."), t("muitas tentativas. Tente amanhã ou entre com o Google."),
];

// modo conversa: gravação com medidor de volume para saber quando a pessoa parou de falar
const VOICE_PRESET: any = { ...RecordingPresets.HIGH_QUALITY, isMeteringEnabled: true };
const EXIT_RE = /^\s*(tchau|encerr(a|ar)|pode parar|parar|sair|fim|obrigad[oa],? (é|e) só isso|bye|goodbye|stop|that'?s all|adi[oó]s)\b/i;

// gravação de reunião: mono, 16 kHz, 32 kbps (1 h ≈ 15 MB) — suficiente para transcrever
const MEETING_PRESET: any = {
  ...RecordingPresets.HIGH_QUALITY, sampleRate: 16000, numberOfChannels: 1, bitRate: 32000,
  android: { ...(RecordingPresets.HIGH_QUALITY as any).android, sampleRate: 16000 },
  ios: { ...(RecordingPresets.HIGH_QUALITY as any).ios, sampleRate: 16000 },
};

const SUGGESTIONS = (): [string, string][] => [
  [t("☀️ Bom dia"), t("Bom dia! O que eu tenho hoje?")],
  [t("💷 Gastos do mês"), t("Quanto eu gastei este mês, por empresa?")],
  [t("📝 Tarefas"), t("Quais são minhas tarefas abertas?")],
  [t("📊 Minha semana"), t("Como foi minha semana?")],
  [t("🔗 Link de agendamento"), t("Me manda meu link de agendamento.")],
  [t("🔁 Assinaturas"), t("Quais assinaturas e cobranças recorrentes eu pago?")],
];
// SHA-256 em JS puro (sem módulo nativo): o app manda ao servidor o hash de um segredo que só ele conhece,
// e depois o segredo, para trocar o código de login. Outro app que capture o link fidus:// não consegue entrar.
function sha256hex(msg: string): string {
  const K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,
    0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,
    0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,
    0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,
    0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  const bytes: number[] = [];
  for (const ch of unescape(encodeURIComponent(msg))) bytes.push(ch.charCodeAt(0));
  const bitLen = bytes.length * 8;
  bytes.push(0x80);
  while (bytes.length % 64 !== 56) bytes.push(0);
  for (let i = 7; i >= 0; i--) bytes.push(i >= 4 ? 0 : (bitLen >>> (i * 8)) & 0xff);
  let H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  const r = (x: number, n: number) => (x >>> n) | (x << (32 - n));
  for (let o = 0; o < bytes.length; o += 64) {
    const w = new Array(64);
    for (let i = 0; i < 16; i++) w[i] = (bytes[o + i * 4] << 24) | (bytes[o + i * 4 + 1] << 16) | (bytes[o + i * 4 + 2] << 8) | bytes[o + i * 4 + 3];
    for (let i = 16; i < 64; i++) {
      const s0 = r(w[i - 15], 7) ^ r(w[i - 15], 18) ^ (w[i - 15] >>> 3), s1 = r(w[i - 2], 17) ^ r(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    let [a, b, c, d, e, f, g, h] = H;
    for (let i = 0; i < 64; i++) {
      const t1 = (h + (r(e, 6) ^ r(e, 11) ^ r(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) | 0;
      const t2 = ((r(a, 2) ^ r(a, 13) ^ r(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
      h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    H = [H[0] + a, H[1] + b, H[2] + c, H[3] + d, H[4] + e, H[5] + f, H[6] + g, H[7] + h].map((x) => x | 0);
  }
  return H.map((x) => (x >>> 0).toString(16).padStart(8, "0")).join("");
}

function randomSecret(): string {
  const buf = new Uint8Array(32);
  const c: any = (globalThis as any).crypto;
  if (c?.getRandomValues) c.getRandomValues(buf);
  else for (let i = 0; i < buf.length; i++) buf[i] = Math.floor(Math.random() * 256) ^ (Date.now() >> (i % 8));
  return Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
}

const DEFAULT_SERVER = "https://fidus.148-230-123-44.sslip.io";
const SUPPORT_EMAIL = "suporte@homb.io";
const PLAN_NAMES: Record<string, string> = { essencial: "Essencial", negocio: "Negócio", premium: "Premium" };
const fmtClock = (sec: number) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
const money = (n: number, sym = "€") => `${sym}${LANG === "pt" ? n.toFixed(2).replace(".", ",") : n.toFixed(2)}`;

type Draft = { to: string; subject: string; body: string; cc?: string; title?: string; start?: string; emails?: string[] };
type Action = { id: string; kind: string; status: string; payload: Draft };
type Doc = { document_id: number; title: string; expires_on?: string | null; url: string };
type Task = { id: number; title: string; due?: string | null; priority: string; status: string; overdue?: boolean };
type Upsell = { feature_label: string; plan: string; name: string; month: number; year: number; highlights: string[];
  current_plan: string; url: string; symbol?: string };
type Item =
  | { id: string; type: "user"; text: string }
  | { id: string; type: "fidus"; text: string }
  | { id: string; type: "action"; action: Action }
  | { id: string; type: "doc"; doc: Doc }
  | { id: string; type: "upsell"; up: Upsell }
  | { id: string; type: "nps" };
type Screen = "chat" | "convs" | "tasks" | "docs" | "meetings" | "expenses" | "booking" | "activity" | "invite" | "admin" | "settings" | "panel";

const NAVY = "#0E1E3A";
const MINT = "#3DDC97";
const BLUE = "#2F6BFF";
const ICON: Record<string, string> = {
  event_created: "📅", event_deleted: "🗑", email_draft: "✉️", expense_added: "💷", expense_deleted: "🗑",
  reminder_created: "⏰", task_added: "📝", task_done: "✅", document_saved: "📄", bill_added: "🔁",
  bill_deleted: "🗑", meet_added: "🎥", invite_draft: "👥", meeting_summarized: "🎙", booking_received: "🗓",
  export_created: "📦", sheet_changed: "📊",
};
const LABEL = (): Record<string, string> => ({
  event_created: t("Agenda"), event_deleted: t("Agenda"), email_draft: t("E-mail"), expense_added: t("Gasto"),
  expense_deleted: t("Gasto"), reminder_created: t("Lembrete"), task_added: t("Tarefa"), task_done: t("Tarefa"),
  document_saved: t("Documento"), bill_added: t("Conta fixa"), bill_deleted: t("Conta fixa"), meet_added: t("Agenda"),
  invite_draft: t("Convite"), meeting_summarized: t("Reunião"), booking_received: t("Agendamento"), export_created: t("Contador"),
  sheet_changed: t("Planilha"),
});
const fmtDay = (d?: string | null) => d ? `${d.slice(8, 10)}/${d.slice(5, 7)}` : "";
// selo de status: verbo claro + cor
const GREEN = "#2E9E6B", RED = "#D64545", AMBER = "#C98A00", GRAY = "#8A94A6";
function pill(kind: string, status: string): { text: string; color: string } {
  if (status === "desfeito") return { text: t("Desfeito"), color: GRAY };
  if (status === "cancelado") return { text: t("Cancelado"), color: GRAY };
  if (status === "aguardando você") return { text: t("Aguardando você"), color: AMBER };
  if (status === "enviado") return { text: t("Enviado"), color: GREEN };
  if (kind === "bill_deleted") return { text: t("Removida"), color: RED };
  if (kind.endsWith("_deleted")) return { text: t("Apagado"), color: RED };
  if (kind === "expense_added") return { text: t("Lançado"), color: GREEN };
  if (kind === "task_done") return { text: t("Concluída"), color: GREEN };
  if (kind === "document_saved") return { text: t("Guardado"), color: GREEN };
  if (kind === "bill_added") return { text: t("Cadastrada"), color: GREEN };
  if (kind === "meeting_summarized") return { text: t("Ata pronta"), color: GREEN };
  if (kind === "booking_received") return { text: t("Agendado"), color: GREEN };
  if (kind === "export_created") return { text: t("Gerado"), color: GREEN };
  if (kind === "sheet_changed") return { text: t("Alterada"), color: GREEN };
  return { text: t("Criado"), color: GREEN };
}
const fmtDate = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

// ---------- Ícones desenhados com Views (sem biblioteca nativa): traço fino, no estilo dos apps de chat ----------
function PlusIcon({ color, size = 20 }: { color: string; size?: number }) {
  const w = 2;
  return (
    <View style={{ width: size, height: size, alignItems: "center", justifyContent: "center" }}>
      <View style={{ position: "absolute", width: size * 0.8, height: w, borderRadius: 1, backgroundColor: color }} />
      <View style={{ position: "absolute", width: w, height: size * 0.8, borderRadius: 1, backgroundColor: color }} />
    </View>
  );
}

function CloseIcon({ color, size = 18 }: { color: string; size?: number }) {
  return (
    <View style={{ width: size, height: size, alignItems: "center", justifyContent: "center" }}>
      <View style={{ position: "absolute", width: size, height: 2, borderRadius: 1, backgroundColor: color, transform: [{ rotate: "45deg" }] }} />
      <View style={{ position: "absolute", width: size, height: 2, borderRadius: 1, backgroundColor: color, transform: [{ rotate: "-45deg" }] }} />
    </View>
  );
}

function MicIcon({ color, size = 22 }: { color: string; size?: number }) {
  const w = size * 0.42, h = size * 0.58;
  return (
    <View style={{ width: size, height: size, alignItems: "center" }}>
      <View style={{ width: w, height: h, borderRadius: w / 2, borderWidth: 1.8, borderColor: color }} />
      <View style={{ position: "absolute", top: size * 0.32, width: size * 0.7, height: size * 0.42, borderWidth: 1.8, borderTopWidth: 0,
        borderColor: color, borderBottomLeftRadius: size * 0.35, borderBottomRightRadius: size * 0.35 }} />
      <View style={{ position: "absolute", top: size * 0.74, width: 1.8, height: size * 0.2, backgroundColor: color }} />
    </View>
  );
}

function ArrowUpIcon({ color, size = 18, down = false }: { color: string; size?: number; down?: boolean }) {
  return (
    <View style={{ width: size, height: size, alignItems: "center", justifyContent: "center", transform: down ? [{ rotate: "180deg" }] : [] }}>
      <View style={{ position: "absolute", top: size * 0.2, width: 2.2, height: size * 0.75, borderRadius: 1, backgroundColor: color }} />
      <View style={{ position: "absolute", top: size * 0.12, width: size * 0.48, height: size * 0.48, borderLeftWidth: 2.2, borderTopWidth: 2.2,
        borderColor: color, transform: [{ rotate: "45deg" }] }} />
    </View>
  );
}

function MenuIcon({ color, size = 22 }: { color: string; size?: number }) {
  return (
    <View style={{ width: size, height: size, justifyContent: "center", gap: size * 0.22 }}>
      <View style={{ width: size * 0.9, height: 2, borderRadius: 1, backgroundColor: color }} />
      <View style={{ width: size * 0.55, height: 2, borderRadius: 1, backgroundColor: color }} />
    </View>
  );
}

function PencilIcon({ color, size = 18 }: { color: string; size?: number }) {
  return (
    <View style={{ width: size, height: size, alignItems: "center", justifyContent: "center" }}>
      <View style={{ width: size * 0.3, height: size * 0.95, borderWidth: 1.6, borderColor: color, borderRadius: 2,
        borderBottomLeftRadius: size * 0.15, borderBottomRightRadius: size * 0.15, transform: [{ rotate: "45deg" }] }} />
      <View style={{ position: "absolute", width: size * 0.3, height: 1.6, backgroundColor: color, top: size * 0.3, left: size * 0.48,
        transform: [{ rotate: "45deg" }] }} />
    </View>
  );
}

function CopyIcon({ color, size = 18 }: { color: string; size?: number }) {
  const b = size * 0.62;
  return (
    <View style={{ width: size, height: size }}>
      <View style={{ position: "absolute", left: 0, top: 0, width: b, height: b, borderRadius: 3, borderWidth: 1.6, borderColor: color }} />
      <View style={{ position: "absolute", right: 0, bottom: 0, width: b, height: b, borderRadius: 3, borderWidth: 1.6, borderColor: color }} />
    </View>
  );
}

function MailIcon({ color, size = 18 }: { color: string; size?: number }) {
  const w = size, h = size * 0.72;
  return (
    <View style={{ width: w, height: size, alignItems: "center", justifyContent: "center" }}>
      <View style={{ width: w, height: h, borderRadius: 3, borderWidth: 1.6, borderColor: color, overflow: "hidden", alignItems: "center" }}>
        <View style={{ width: w * 0.62, height: w * 0.62, marginTop: -w * 0.36, borderWidth: 1.6, borderColor: color, transform: [{ rotate: "45deg" }] }} />
      </View>
    </View>
  );
}

function ComposeIcon({ color, size = 22 }: { color: string; size?: number }) {
  return (
    <View style={{ width: size, height: size, alignItems: "center", justifyContent: "center" }}>
      <View style={{ position: "absolute", width: size * 0.82, height: size * 0.82, borderRadius: size * 0.22, borderWidth: 1.8, borderColor: color }} />
      <PlusIcon color={color} size={size * 0.5} />
    </View>
  );
}

function WaveIcon({ color, size = 20 }: { color: string; size?: number }) {
  const hs = [0.35, 0.75, 1, 0.6];
  return (
    <View style={{ width: size, height: size, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 2.5 }}>
      {hs.map((h, i) => <View key={i} style={{ width: 2.6, height: size * h, borderRadius: 2, backgroundColor: color }} />)}
    </View>
  );
}

// Barrinhas que se mexem enquanto grava (mostra que está ouvindo)
function RecordingBars({ color }: { color: string }) {
  const vals = useRef([0, 1, 2, 3, 4, 5, 6].map(() => new Animated.Value(0.3))).current;
  useEffect(() => {
    const loops = vals.map((v, i) => Animated.loop(Animated.sequence([
      Animated.timing(v, { toValue: 1, duration: 300 + i * 70, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      Animated.timing(v, { toValue: 0.25, duration: 300 + i * 70, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
    ])));
    loops.forEach((l) => l.start());
    return () => loops.forEach((l) => l.stop());
  }, []);
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 3, height: 22 }}>
      {vals.map((v, i) => (
        <Animated.View key={i} style={{ width: 3, height: 22, borderRadius: 2, backgroundColor: color, transform: [{ scaleY: v }] }} />
      ))}
    </View>
  );
}

// Texto com links, e-mails e telefones tocáveis (abre navegador, e-mail ou discador)
const LINK_RE = /(\[[^\]\n]{1,80}\]\((https?:\/\/[^\s)]+)\))|(https?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]])|(www\.[^\s<>"']+[^\s<>"'.,;:!?)\]])|([\w.+-]+@[\w-]+\.[\w.-]*[a-z]{2,})|((?:\+|00)\d[\d\s-]{7,16}\d)/gi;

function LinkText({ text, style, linkColor }: { text: string; style: any; linkColor: string }) {
  const parts: any[] = [];
  let last = 0, m: RegExpExecArray | null, k = 0;
  LINK_RE.lastIndex = 0;
  while ((m = LINK_RE.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    let label = m[0], url = m[0];
    if (m[1]) { label = m[1].slice(1, m[1].indexOf("](")); url = m[2]; }
    else if (m[4]) url = "https://" + m[4];
    else if (m[5]) url = "mailto:" + m[5];
    else if (m[6]) url = "tel:" + m[6].replace(/[\s-]/g, "").replace(/^00/, "+");
    const target = url;
    parts.push(
      <Text key={k++} style={{ color: linkColor, textDecorationLine: "underline" }}
        onPress={() => Linking.openURL(target).catch(() => Alert.alert(t("Link"), t("Não consegui abrir este link.")))}>{label}</Text>);
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <Text selectable style={style}>{parts}</Text>;
}

// Corpo de e-mail com **negrito** e listas com • (igual ao que o destinatário vai ver)
function FormattedText({ text, color }: { text: string; color: string }) {
  const inline = (line: string, key: string) => line.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((p, i) =>
    p.startsWith("**") && p.endsWith("**")
      ? <Text key={`${key}-${i}`} style={{ fontWeight: "700" }}>{p.slice(2, -2)}</Text>
      : <Text key={`${key}-${i}`}>{p}</Text>);
  return (
    <View style={{ gap: 2 }}>
      {(text || "").split("\n").map((line, i) => {
        const b = line.match(/^\s*(?:•|-|\*)\s+(.*)$/);
        if (b) return (
          <View key={i} style={{ flexDirection: "row", paddingLeft: 4 }}>
            <Text style={{ color, width: 16, lineHeight: 24, fontSize: 16 }}>•</Text>
            <Text selectable style={{ color, flex: 1, lineHeight: 24, fontSize: 16 }}>{inline(b[1], String(i))}</Text>
          </View>);
        if (!line.trim()) return <View key={i} style={{ height: 8 }} />;
        return <Text key={i} selectable style={{ color, lineHeight: 24, fontSize: 16 }}>{inline(line, String(i))}</Text>;
      })}
    </View>
  );
}

function Card({ c, children, onPress, style }: any) {
  return <Pressable onPress={onPress} disabled={!onPress} style={[s.actCard, { backgroundColor: c.card }, style]}>{children}</Pressable>;
}

// Cartão de e-mail no estilo do Claude: cabeçalho com editar, copiar e enviar; destinatário, assunto e texto formatado
function EmailCard({ a, c, dark, onSend, onCancel, onSave, onCopy, onEditing }: {
  a: Action; c: any; dark: boolean; onSend: () => void; onCancel: () => void;
  onSave: (p: { to: string; subject: string; body: string }) => Promise<boolean>; onCopy: (text: string) => void;
  onEditing: (on: boolean) => void;
}) {
  const [editing, setEditingRaw] = useState(false);
  const setEditing = (on: boolean) => { setEditingRaw(on); onEditing(on); };  // em edição, "envia" não manda este rascunho
  const [to, setTo] = useState(a.payload.to);
  const [subject, setSubject] = useState(a.payload.subject);
  const [body, setBody] = useState(a.payload.body);
  const pending = a.status === "pending";
  const line = dark ? "#26375A" : "#E3E8F0";
  const statusText = a.status === "sending" ? t("Enviando…") : a.status === "sent" ? t("Enviado ✓") : a.status === "cancelled" ? t("Descartado") : "";
  return (
    <View style={[s.emailCard, { backgroundColor: c.card, borderColor: line }]}>
      <View style={[s.emailHead, { borderBottomColor: line }]}>
        <MailIcon color={c.sub} size={17} />
        <Text style={{ color: c.text, fontWeight: "700", fontSize: 15, flex: 1, marginLeft: 8 }}>{t("Email")}</Text>
        {pending && !editing && (
          <Pressable hitSlop={8} onPress={() => setEditing(true)} style={s.headBtn} accessibilityLabel={t("Editar")}>
            <PencilIcon color={c.sub} /></Pressable>)}
        <Pressable hitSlop={8} style={s.headBtn} accessibilityLabel={t("Copiar")}
          onPress={() => onCopy(`${t("Para")}: ${to}\n${t("Assunto")}: ${subject}\n\n${body.replace(/\*\*/g, "")}`)}>
          <CopyIcon color={c.sub} /></Pressable>
        {pending && !editing && (
          <Pressable onPress={onSend} accessibilityLabel={t("Enviar")} style={[s.sendBlue, { backgroundColor: BLUE }]}>
            <ArrowUpIcon color="#fff" size={16} /></Pressable>)}
        {!!statusText && <Text style={{ color: a.status === "sent" ? GREEN : c.sub, fontSize: 12, fontWeight: "600", marginLeft: 6 }}>{statusText}</Text>}
      </View>
      {editing ? (
        <View style={{ padding: 14, gap: 8 }}>
          <Text style={{ color: c.sub, fontSize: 12 }}>{t("Para")}</Text>
          <TextInput value={to} onChangeText={setTo} autoCapitalize="none" keyboardType="email-address"
            style={[s.editInput, { color: c.text, borderColor: line }]} />
          <Text style={{ color: c.sub, fontSize: 12 }}>{t("Assunto")}</Text>
          <TextInput value={subject} onChangeText={setSubject} style={[s.editInput, { color: c.text, borderColor: line }]} />
          <TextInput value={body} onChangeText={setBody} multiline
            style={[s.editInput, { color: c.text, borderColor: line, minHeight: 160, textAlignVertical: "top" }]} />
          <View style={s.row}>
            <Pressable style={[s.secondary, { borderColor: c.sub }]} onPress={() => {
              setTo(a.payload.to); setSubject(a.payload.subject); setBody(a.payload.body); setEditing(false); }}>
              <Text style={{ color: c.text }}>{t("Cancelar")}</Text></Pressable>
            <Pressable style={[s.primarySm, { backgroundColor: BLUE }]} onPress={async () => {
              if (await onSave({ to, subject, body })) setEditing(false); }}>
              <Text style={s.primaryText}>{t("Salvar")}</Text></Pressable>
          </View>
        </View>
      ) : (<>
        <View style={[s.emailRow, { borderBottomColor: line }]}>
          <Text style={{ color: c.sub, width: 64 }}>{t("Para")}</Text>
          <Text selectable style={{ color: c.text, flex: 1, fontSize: 15 }}>{to}</Text>
        </View>
        <View style={[s.emailRow, { borderBottomColor: line }]}>
          <Text style={{ color: c.sub, width: 64 }}>{t("Assunto")}</Text>
          <Text selectable style={{ color: c.text, flex: 1, fontWeight: "700" }}>{subject}</Text>
        </View>
        <View style={{ padding: 14 }}><FormattedText text={body} color={c.text} /></View>
        {pending && (
          <View style={[s.emailFoot, { borderTopColor: line }]}>
            <Text style={{ color: c.sub, fontSize: 12, flex: 1 }}>{t("Toque na seta azul ou diga “envia”.")}</Text>
            <Pressable hitSlop={8} onPress={onCancel}><Text style={{ color: c.sub, fontSize: 13, textDecorationLine: "underline" }}>{t("Descartar")}</Text></Pressable>
          </View>)}
      </>)}
    </View>
  );
}

export default function App() {
  return <SafeAreaProvider><FidusApp /></SafeAreaProvider>;
}

function FidusApp() {
  const dark = useColorScheme() === "dark";
  const c = dark ? { bg: "#0B1426", card: "#14223F", text: "#EEF2F8", sub: "#9AA8C0", line: "#24365A" }
                 : { bg: "#F5F7FB", card: "#FFFFFF", text: NAVY, sub: "#5B6B85", line: "#DDE3EC" };

  const [, setTrVer] = useState(0);
  const [server, setServer] = useState(DEFAULT_SERVER);
  const [loginCode, setLoginCode] = useState("");
  const [refCode, setRefCode] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loggingIn, setLoggingIn] = useState(false);
  const [me, setMe] = useState<any>(null);
  const [admin, setAdmin] = useState<{ users: any[]; invites: any[] }>({ users: [], invites: [] });
  const [adminLoading, setAdminLoading] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [token, setToken] = useState("");
  const [configured, setConfigured] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const meetRec = useAudioRecorder(MEETING_PRESET);
  const voiceRec = useAudioRecorder(VOICE_PRESET);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [vState, setVState] = useState<"listening" | "thinking" | "speaking" | "idle">("idle");
  const [vHeard, setVHeard] = useState("");
  const [vReply, setVReply] = useState("");
  const voiceActive = useRef(false);
  const vad = useRef({ t0: 0, floor: -60, samples: [] as number[], speechAt: 0, lastLoud: 0, timer: null as any });
  const sr = useRef({ on: false, text: "", empty: 0, failed: false });  // transcrição no celular
  const srHandlers = useRef<any>({});
  const clip = useRef<any>(null);       // voz natural tocando agora
  const phraseAudio = useRef<Record<string, string>>({});  // frases fixas já em voz natural
  const pulse = useRef(new Animated.Value(1)).current;
  const [meeting, setMeeting] = useState(false);
  const [meetSecs, setMeetSecs] = useState(0);
  const [plan, setPlan] = useState<any>(null);
  const [sheet, setSheet] = useState<{ title: string; items: [string, () => void][] } | null>(null);
  const [recording, setRecording] = useState(false);
  const [recSecs, setRecSecs] = useState(0);
  const [busy, setBusy] = useState(false);
  const [typed, setTyped] = useState("");
  const listRef = useRef<FlatList>(null);
  const insets = useSafeAreaInsets();
  const [kb, setKb] = useState(0);
  const [screen, setScreen] = useState<Screen>("chat");
  const [acts, setActs] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [newTask, setNewTask] = useState("");
  const [actsLoading, setActsLoading] = useState(false);
  // menu lateral e telas do menu
  const [drawer, setDrawer] = useState(false);
  const drawerX = useRef(new Animated.Value(-340)).current;
  const [convs, setConvs] = useState<any[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [docQuery, setDocQuery] = useState("");
  const [meetings, setMeetings] = useState<any>(null);
  const [expenses, setExpenses] = useState<any>(null);
  const [expMonth, setExpMonth] = useState("");
  const [expWallet, setExpWallet] = useState("");  // "" = todas as carteiras
  const [expLock, setExpLock] = useState<any>(null);
  const [newWallet, setNewWallet] = useState<{ name: string; currency: string } | null>(null);
  const [booking, setBooking] = useState<any>(null);
  const [referral, setReferral] = useState<any>(null);
  const [refApply, setRefApply] = useState("");
  const [loadingScreen, setLoadingScreen] = useState(false);
  const [reader, setReader] = useState<{ title: string; text: string } | null>(null);
  const [toast, setToast] = useState("");
  const [atBottom, setAtBottom] = useState(true);
  const [nameEdit, setNameEdit] = useState("");
  const [pendingMeet, setPendingMeet] = useState<string | null>(null);
  const [billing, setBilling] = useState<any>(null);
  const [fb, setFb] = useState<Record<string, number>>({});
  const [npsScore, setNpsScore] = useState<number | null>(null);
  const [npsText, setNpsText] = useState("");
  const [panel, setPanel] = useState<any>(null);
  const [authOpts, setAuthOpts] = useState<any>(null);
  const [emailMode, setEmailMode] = useState(false);
  const [loginEmail, setLoginEmail] = useState("");
  const [emailSent, setEmailSent] = useState(false);
  const [emailCode, setEmailCode] = useState("");
  const [lockAvail, setLockAvail] = useState(false);
  const [lockOn, setLockOn] = useState(false);
  const [activeReq, setActiveReq] = useState("");  // pedido em andamento que pode ser parado
  const cancelledReqs = useRef(new Set<string>());
  const [speakAudio, setSpeakAudio] = useState(false);  // áudio gravado: responder também em voz alta (desligado por padrão; só o modo conversa fala sempre)
  const [locked, setLocked] = useState(false);
  const bgAt = useRef(0);
  const kicked = useRef(false);
  const [device, setDevice] = useState<any>(null);
  const [storeReady, setStoreReady] = useState(false);
  // rascunhos na tela e fora de edição: só esses podem sair quando o usuário diz "envia"
  const itemsRef = useRef<Item[]>([]);
  itemsRef.current = items;
  const editingIds = useRef(new Set<string>());
  const visibleDrafts = () => itemsRef.current
    .filter((it) => it.type === "action" && it.action.status === "pending" && !editingIds.current.has(it.action.id))
    .map((it: any) => it.action.id as string);

  const bump = () => setTrVer((v) => v + 1);
  const flash = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 1800); };

  // ---------- Idioma ----------
  async function loadLang(lang: string) {
    LANG = (lang || "pt").split("-")[0].toLowerCase();
    if (LANG === "pt") { TR = {}; bump(); return; }
    let cacheFile: any = null;
    try {
      cacheFile = new File(Paths.document, `i18n-${LANG}.json`);
      if (cacheFile.exists) { TR = JSON.parse(cacheFile.textSync()); bump(); }
    } catch { /* sem cópia no celular */ }
    try {
      const r = await fetch(base() + "/v1/i18n", { method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token.trim()}` } : {}) },
        body: JSON.stringify({ lang: LANG, strings: I18N_KEYS }) });
      const j = await r.json();
      if (j?.strings && Object.keys(j.strings).length) {
        TR = { ...TR, ...j.strings }; bump();
        try { if (cacheFile) { if (!cacheFile.exists) cacheFile.create(); cacheFile.write(JSON.stringify(TR)); } } catch {}
      }
    } catch { /* sem rede: fica com a cópia ou o português */ }
  }

  useEffect(() => {  // tela de entrada já no idioma do celular
    LOCALE = deviceLocale();
    loadLang(LOCALE);
    fetch(DEFAULT_SERVER + "/v1/auth/options").then((r) => r.json()).then(setAuthOpts).catch(() => {});
  }, []);

  // Android (tela cheia): o teclado cobre o app, então empurramos o conteúdo para cima
  useEffect(() => {
    if (Platform.OS !== "android") return;
    const show = Keyboard.addListener("keyboardDidShow", (e) => {
      setKb(e.endCoordinates.height);
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 80);
    });
    const hide = Keyboard.addListener("keyboardDidHide", () => setKb(0));
    return () => { show.remove(); hide.remove(); };
  }, []);

  async function loadHistory(): Promise<any[] | null> {
    try {
      const msgs = (await api("/v1/history", {}, 15000)).messages || [];
      histLen.current = msgs.length;
      setItems((prev) => [
        ...msgs.map((m: any) => ({ id: uid(), type: m.role === "user" ? "user" : "fidus", text: m.text } as Item)),
        ...prev.filter((it) => it.type === "action"),  // mantém os cartões de rascunho na tela
      ]);
      setTimeout(() => listRef.current?.scrollToEnd({ animated: false }), 100);
      return msgs;
    } catch { return null; }
  }

  async function loadWaitingDrafts() {  // rascunhos que ainda esperam você voltam a aparecer ao abrir o app
    try {
      const r = await api("/v1/actions", {}, 15000);
      setItems((prev) => {
        const have = new Set(prev.filter((it) => it.type === "action").map((it: any) => it.action.id));
        return [...prev, ...(r.actions || []).filter((a: Action) => !have.has(a.id)).map((a: Action) => ({ id: uid(), type: "action", action: a } as Item))];
      });
    } catch { /* servidor antigo */ }
  }

  // ao abrir: idioma/país do celular, conversa salva, "bom dia" na primeira abertura do dia
  useEffect(() => {
    if (!configured) return;
    (async () => {
      try {
        const loc = deviceLocale(); const region = (loc.split("-")[1] || "").toUpperCase();
        await api("/v1/profile", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ language: loc, ...(/^[A-Z]{2}$/.test(region) ? { country: region } : {}),
            ...(deviceTimezone() ? { timezone: deviceTimezone() } : {}), only_if_empty: true }) }, 15000);
      } catch { /* servidor antigo */ }
      for (let i = 0; i < 3; i++) {  // dados da conta; tenta de novo se a rede falhar
        try {
          const m = await api("/v1/me", {}, 15000); setMe(m); if (m.language && m.language !== LANG) loadLang(m.language);
          if (m.nps_due) {  // nota de 0 a 10, no máximo uma vez por mês (se a pessoa fechar, volta em 7 dias)
            const skip = Number(await SecureStore.getItemAsync("npsSkip") || 0);
            if (Date.now() - skip > 7 * 86400000) setTimeout(() => push({ id: uid(), type: "nps" }), 4000);
          }
          break;
        }
        catch { await new Promise((r) => setTimeout(r, 3000)); }
      }
      await loadHistory();
      await loadWaitingDrafts();
      const n = new Date();
      const today = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
      try {
        if ((await SecureStore.getItemAsync("lastBrief")) !== today) {
          const b = await api("/v1/briefing", {}, 45000);
          if (b?.text) { push({ id: uid(), type: "fidus", text: b.text }); await SecureStore.setItemAsync("lastBrief", today); }
        }
      } catch { /* sem bom dia hoje */ }
      try {  // segunda-feira: resumo da semana
        if (new Date().getDay() === 1 && (await SecureStore.getItemAsync("lastWeekly")) !== today) {
          const w = await api("/v1/weekly", {}, 45000);
          if (w?.text) { push({ id: uid(), type: "fidus", text: w.text }); await SecureStore.setItemAsync("lastWeekly", today); }
        }
      } catch { /* sem resumo semanal */ }
      setupNotifications();
      try { setPlan(await api("/v1/plan", {}, 15000)); } catch { /* servidor antigo */ }
      setupStore();
    })();
  }, [configured]);

  // ---------- Assinatura na loja (RevenueCat) ----------
  async function setupStore() {
    try {
      const b = await api("/v1/billing", {}, 15000);
      setBilling(b);
      const key = Platform.OS === "ios" ? b.ios_key : b.android_key;
      if (!Purchases || !b.enabled || !key) return;
      Purchases.configure({ apiKey: key, appUserID: b.app_user_id });  // o aviso da loja chega ao servidor com o id do cliente
      setStoreReady(true);
    } catch (e: any) { console.log("[Fidus] loja", e?.message ?? e); setStoreReady(false); }
  }

  async function waitForPlan(target: string) {  // o aviso da loja leva alguns segundos para chegar ao servidor
    for (let i = 0; i < 8; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try { const p = await api("/v1/plan", {}, 15000); setPlan(p); if (p.plan === target) return true; } catch {}
    }
    return false;
  }

  async function buy(pkg: any, planId: string, planName: string) {
    try {
      let change: any = null;
      if (Platform.OS === "android") {  // troca de plano na Google Play: substitui a assinatura atual
        try {
          const info = await Purchases.getCustomerInfo();
          const cur = (info?.activeSubscriptions || [])[0];
          if (cur) change = { oldProductIdentifier: String(cur).split(":")[0] };
        } catch {}
      }
      const trial = billing?.referral_trial
        ? (pkg.product?.subscriptionOptions || []).find((o: any) => (o.tags || []).includes(billing.trial_offer_tag || "convite"))
        : null;
      if (trial) await Purchases.purchaseSubscriptionOption(trial, change || undefined);
      else await Purchases.purchasePackage(pkg, null, change || undefined);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      flash(t("Assinatura confirmada"));
      const ok = await waitForPlan(planId);
      if (!ok) Alert.alert(t("Plano {0}", t(planName)), t("A loja confirmou o pagamento. O plano novo aparece em alguns minutos."));
    } catch (e: any) {
      if (e?.userCancelled) return;
      Alert.alert(t("Assinatura"), e?.message ?? String(e));
    }
  }

  async function restorePurchases() {
    if (!storeReady) return;
    try { await Purchases.restorePurchases(); flash(t("Compras restauradas")); setTimeout(() => loadScreen("settings"), 2500); }
    catch (e: any) { Alert.alert(t("Assinatura"), e?.message ?? String(e)); }
  }

  // a conexão caiu no meio (troca de rede, 4G fraco, app em segundo plano). O servidor
  // normalmente termina o pedido mesmo assim, então buscamos a resposta no histórico.
  const isNetErr = (e: any) => !/^\d{3}:/.test(e?.message ?? "") && e?.name !== "AbortError";
  async function recover(e: any, before: number) {
    if (!isNetErr(e)) return push({ id: uid(), type: "fidus", text: `${t("Erro")}: ${e?.message ?? e}` });
    push({ id: uid(), type: "fidus", text: t("A conexão caiu. Buscando a resposta no servidor…") });
    for (let i = 0; i < 12; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      const msgs = await loadHistory();
      if (msgs && msgs.length > before && msgs[msgs.length - 1].role === "assistant") return;
    }
    push({ id: uid(), type: "fidus", text: t("Não consegui buscar a resposta. Confira sua internet e veja a Atividade antes de repetir o pedido.") });
  }
  const histLen = useRef(0);  // quantas mensagens o servidor tinha na última vez que olhamos
  const historyCount = () => histLen.current;

  useEffect(() => {
    (async () => {
      const sv = await SecureStore.getItemAsync("server");
      const tk = await SecureStore.getItemAsync("token");
      if (sv && tk) { setServer(sv); setToken(tk); setConfigured(true); }
    })();
  }, []);

  const push = (it: Item) => {
    setItems((prev) => [...prev, it]);
    setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 50);
  };
  const uid = () => Math.random().toString(36).slice(2);

  const base = () => server.trim().replace(/\/$/, "");

  async function api(path: string, init: RequestInit = {}, timeoutMs = 180000) {
    const url = base() + path;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const r = await fetch(url, {
        ...init, signal: ctrl.signal,
        headers: { Authorization: `Bearer ${token.trim()}`, "X-Fidus-Client": CLIENT_CAPS, ...(init.headers || {}) },
      });
      if (!r.ok) {
        const body = await r.text();
        if (r.status === 401 && token && !kicked.current && /outro_aparelho|"saiu"|token inválido/.test(body)) {
          kicked.current = true;  // conta aberta em outro celular (um aparelho por conta) ou acesso encerrado
          setTimeout(() => {
            Alert.alert(t("Você saiu deste aparelho"), /outro_aparelho/.test(body)
              ? t("Sua conta do Fidus foi aberta em outro aparelho. Cada conta funciona em um aparelho por vez. Para usar aqui, entre de novo.")
              : t("Seu acesso foi encerrado. Entre de novo para continuar."));
            logoutLocal();
          }, 100);
        }
        throw new Error(`${r.status}: ${body}`);
      }
      return r.json();
    } catch (e: any) {
      console.log("[Fidus] erro", path, e?.message ?? e);
      if (e?.name === "AbortError") throw new Error(t("o servidor demorou demais para responder"));
      throw e;
    } finally { clearTimeout(timer); }
  }
  const post = (path: string, body: any = {}, timeoutMs?: number) =>
    api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, timeoutMs);
  const errMsg = (e: any) => String(e?.message ?? e).replace(/^\d{3}: /, "").replace(/^\{"detail":"(.*)"\}$/, "$1");

  async function testConnection() {
    try {
      const h = await api("/health", {}, 15000);
      Alert.alert(t("Conexão"), `${t("Conexão ok.")} Google: ${h.google_connected ? t("conectado") : t("não conectado")}.`);
    } catch (e: any) { Alert.alert(t("Conexão"), `${t("Erro de conexão")}: ${errMsg(e)}`); }
  }

  async function loadActivity() {
    setActsLoading(true);
    try { const r = await api("/v1/activity", {}, 15000); setActs(r.items || []); setStats(r.stats || null); }
    catch (e: any) { Alert.alert(t("Atividade"), errMsg(e)); }
    finally { setActsLoading(false); }
  }

  // Avisos agendados no próprio celular (não precisa de Firebase): bom dia às 8h e semana na segunda
  async function setupNotifications() {
    if (!Notifications) return;
    try {
      Notifications.setNotificationHandler({
        handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: false, shouldShowAlert: true }),
      });
      if (Platform.OS === "android")
        await Notifications.setNotificationChannelAsync("fidus", { name: "Fidus", importance: Notifications.AndroidImportance.HIGH });
      const perm = await Notifications.requestPermissionsAsync();
      if (!perm.granted) return;
      const ver = `2-${LANG}`;  // agenda de novo quando o idioma muda
      if ((await SecureStore.getItemAsync("notifV")) === ver) return;
      await Notifications.cancelAllScheduledNotificationsAsync();
      const T = Notifications.SchedulableTriggerInputTypes;
      await Notifications.scheduleNotificationAsync({
        content: { title: t("Bom dia ☀️"), body: t("Sua agenda, tarefas e contas de hoje estão prontas no Fidus.") },
        trigger: { type: T.DAILY, hour: 8, minute: 0, channelId: "fidus" },
      });
      await Notifications.scheduleNotificationAsync({
        content: { title: t("Sua semana com o Fidus 📊"), body: t("Veja o que foi resolvido e o que vem pela frente.") },
        trigger: { type: T.WEEKLY, weekday: 2, hour: 8, minute: 5, channelId: "fidus" },
      });
      await SecureStore.setItemAsync("notifV", ver);
    } catch (e: any) { console.log("[Fidus] notificações", e?.message ?? e); }
  }

  // ---------- Reunião: gravar e gerar a ata ----------
  useEffect(() => {
    if (!meeting) return;
    const t0 = Date.now();
    const iv = setInterval(() => setMeetSecs(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(iv);
  }, [meeting]);

  async function startMeeting() {
    if (busy || recording || meeting) return;
    try {
      const perm = await AudioModule.requestRecordingPermissionsAsync();
      if (!perm.granted) return fail(t("permissão do microfone negada."));
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true, allowsBackgroundRecording: true,
                                shouldPlayInBackground: true } as any);
      await meetRec.prepareToRecordAsync();
      meetRec.record();
      try { await KeepAwake?.activateKeepAwakeAsync("meeting"); } catch {}
      setMeetSecs(0); setMeeting(true); setScreen("chat");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch (e: any) { fail(`${t("ao iniciar a gravação da reunião")}: ${e?.message ?? e}`); }
  }

  function upsellCard(feature: string, planId = "negocio") {
    const p = (plan?.plans || []).find((x: any) => x.id === planId);
    if (!p) return false;
    push({ id: uid(), type: "upsell", up: { feature_label: feature, plan: p.id, name: p.name, month: p.month, year: p.year,
      highlights: p.highlights, current_plan: plan.name, url: plan.url, symbol: plan.symbol } });
    return true;
  }

  function meetingMenu() {
    if (meeting) return finishMeeting();
    if (plan?.locked_features?.includes("meetings_record")) {
      push({ id: uid(), type: "fidus", text: t("Gravar reuniões e gerar a ata faz parte do plano Negócio.") });
      if (upsellCard("gravar reuniões e gerar a ata")) return;
    }
    Alert.alert(t("Gravar reunião"), t("Deixe o celular na mesa. No fim, o Fidus transcreve, resume e cria suas tarefas.") + "\n\n"
      + (KeepAwake ? "" : t("Mantenha a tela ligada e o Fidus aberto durante a gravação.") + "\n\n")
      + t("Avise os participantes que a reunião está sendo gravada."), [
      { text: t("Cancelar"), style: "cancel" },
      { text: t("Começar"), onPress: startMeeting },
    ]);
  }

  async function stopMeetingRecorder() {
    try { await meetRec.stop(); } catch {}
    try { KeepAwake?.deactivateKeepAwake("meeting"); } catch {}
    setMeeting(false);
  }

  function finishMeeting() {
    Alert.alert(t("Encerrar reunião?"), t("{0} gravados.", fmtClock(meetSecs)), [
      { text: t("Continuar gravando"), style: "cancel" },
      { text: t("Descartar"), style: "destructive", onPress: () => stopMeetingRecorder() },
      { text: t("Gerar ata"), onPress: uploadMeeting },
    ]);
  }

  async function uploadMeeting() {
    const secs = meetSecs;
    await stopMeetingRecorder();
    const uri = meetRec.uri;
    if (!uri) return fail(t("nenhum áudio foi gravado."));
    push({ id: uid(), type: "user", text: `🎙 ${t("Reunião gravada")} (${fmtClock(secs)})` });
    await sendMeetingFile(uri);
  }

  async function sendMeetingFile(uri: string) {
    await SecureStore.setItemAsync("pendingMeeting", uri);  // se o envio falhar, dá para reenviar pelo menu
    setBusy(true);
    try {
      const audio_b64 = await new File(uri).base64();
      const ext = (uri.match(/\.[a-z0-9]+$/i)?.[0] || ".m4a").toLowerCase();
      const r = await post("/v1/meeting_b64", { audio_b64, ext }, 600000);
      await SecureStore.deleteItemAsync("pendingMeeting");
      if (r.locked) return showResult({ upsell: r.upsell }, false);
      push({ id: uid(), type: "fidus", text: t("Recebi a gravação. Estou transcrevendo e preparando a ata; aviso aqui quando ficar pronta (leva alguns minutos).") });
      pollMeeting(r.meeting_id);
    } catch (e: any) { fail(`${t("ao enviar a reunião")}: ${e?.message ?? e}. ${t("A gravação ficou guardada: abra o menu > Configurações > Reenviar reunião.")}`); }
    finally { setBusy(false); }
  }

  async function pollMeeting(id: number) {
    for (let i = 0; i < 240; i++) {  // até ~1 h com o app aberto; se fechar, a ata aparece na conversa ao reabrir
      await new Promise((r) => setTimeout(r, 15000));
      try {
        const st = await api(`/v1/meetings/${id}`, {}, 15000);
        if (st.status === "pronta") {
          histLen.current += 1;
          push({ id: uid(), type: "fidus", text: st.text });
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
          try { await Notifications?.scheduleNotificationAsync({ content: { title: t("Ata pronta 🎙"), body: st.title || t("Sua reunião") }, trigger: null }); } catch {}
          return;
        }
        if (st.status === "erro") return fail(`${t("na ata")}: ${st.error}`);
      } catch { /* rede instável: tenta de novo */ }
    }
  }

  // ---------- Modo conversa (mãos livres) ----------
  useEffect(() => {
    if (!voiceOpen) return;
    const speed = vState === "listening" ? 700 : vState === "speaking" ? 450 : 1100;
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(pulse, { toValue: 1.12, duration: speed, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      Animated.timing(pulse, { toValue: 1, duration: speed, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [voiceOpen, vState]);

  // ---------- Voz natural (Google) e frases fixas ----------
  // (lista para a tradução: estas frases são faladas pelo nome, não aparecem em t("...") literal em outro lugar)
  const _PHRASE_KEYS = () => [t("Um instante."), t("Deixa eu ver."), t("Já vejo isso."), t("Feito.")];
  const PHRASES = ["Pode falar.", "Um instante.", "Deixa eu ver.", "Já vejo isso.", "Até mais!", "Não entendi. Pode repetir?",
    "Perdi a conexão com o servidor. Tente de novo em instantes.", "Feito."];

  async function preloadPhrases() {
    if (!me?.natural_voice || !createPlayer) return;
    for (const p of PHRASES) {
      if (phraseAudio.current[`${LANG}|${p}`]) continue;
      try { const r = await post("/v1/tts", { phrase: p }, 15000); if (r.audio) phraseAudio.current[`${LANG}|${p}`] = r.audio; } catch { return; }
    }
  }

  function stopClip() {
    try { clip.current?.pause(); } catch {}
    try { clip.current?.remove(); } catch {}
    clip.current = null;
  }

  // toca o MP3 (base64); devolve false se não deu (aí quem chamou usa a voz do celular)
  function playClip(b64: string, onDone?: () => void): boolean {
    if (!createPlayer || !b64) return false;
    try {
      stopClip();
      const f = new File(Paths.cache, `fidus-voz-${Date.now()}.mp3`);
      const bin = atob(b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      f.create(); f.write(bytes);
      const pl = createPlayer({ uri: f.uri });
      clip.current = pl;
      let done = false;
      const finish = () => { if (done) return; done = true; try { f.delete(); } catch {} ; if (clip.current === pl) stopClip(); onDone?.(); };
      pl.addListener("playbackStatusUpdate", (st: any) => { if (st?.didJustFinish) finish(); });
      setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true }).catch(() => {}).finally(() => pl.play());
      return true;
    } catch { return false; }
  }

  useEffect(() => { if (me?.natural_voice) preloadPhrases(); }, [me?.natural_voice, LANG]);

  async function openVoice() {
    if (busy || recording || meeting) return;
    const perm = await AudioModule.requestRecordingPermissionsAsync();
    if (!perm.granted) return fail(t("permissão do microfone negada."));
    if (SpeechRec && !sr.current.failed) {
      try { const p2 = await SpeechRec.requestPermissionsAsync(); if (!p2?.granted) sr.current.failed = true; } catch { sr.current.failed = true; }
    }
    voiceActive.current = true;
    setVHeard(""); setVReply(Speech || me?.natural_voice ? t("Pode falar. Eu escuto e respondo em voz alta.") :
      t("Pode falar. (Para ouvir as respostas em voz alta, instale o APK novo.)"));
    setVoiceOpen(true);
    try { await KeepAwake?.activateKeepAwakeAsync("voice"); } catch {}
    speak(t("Pode falar."), undefined, "Pode falar.");
    preloadPhrases();
  }

  async function closeVoice() {
    voiceActive.current = false;
    clearInterval(vad.current.timer);
    try { Speech?.stop(); } catch {}
    stopClip();
    if (sr.current.on) { try { SpeechRec.abort(); } catch {} ; sr.current.on = false; }
    try { await voiceRec.stop(); } catch {}
    try { KeepAwake?.deactivateKeepAwake("voice"); } catch {}
    setVoiceOpen(false); setVState("idle");
  }

  function ttsLanguage() {
    const dev = deviceLocale();
    return dev.split("-")[0].toLowerCase() === LANG ? dev : (TTS_LOCALE[LANG] || LANG);
  }

  // fala e depois volta a ouvir: voz natural se veio o áudio (ou a frase fixa já carregada), senão a do celular
  function speak(text: string, audio?: string | null, phrase?: string) {
    if (!voiceActive.current) return;
    const mp3 = audio || (phrase ? phraseAudio.current[`${LANG}|${phrase}`] : null);
    try { Speech?.stop(); } catch {}
    if (mp3) {
      setVState("speaking");
      if (playClip(mp3, () => { if (voiceActive.current) listen(); })) return;
    }
    // frase fixa ainda sem a voz natural: não mistura com a voz robótica, só volta a ouvir
    if (!Speech || (phrase && me?.natural_voice && createPlayer)) { setTimeout(listen, phrase ? 150 : 1200); return; }
    setVState("speaking");
    Speech.speak(text, {
      language: ttsLanguage(), rate: 1.02,
      onDone: () => { if (voiceActive.current) listen(); },
      onError: () => { if (voiceActive.current) listen(); },
    });
  }

  // transcrição no celular: o texto aparece enquanto a pessoa fala e sai pronto quando ela para
  srHandlers.current = {
    result: (e: any) => {
      const txt = (e?.results?.[0]?.transcript || "").trim();
      if (txt) { sr.current.text = txt; setVHeard(txt); }
    },
    end: () => {
      if (!sr.current.on) return;
      sr.current.on = false;
      if (!voiceActive.current) return;
      const txt = sr.current.text.trim();
      if (txt) { sr.current.empty = 0; submitVoiceText(txt); return; }
      sr.current.empty += 1;  // ninguém falou: volta a ouvir (e para de insistir depois de um tempo)
      if (sr.current.empty <= 6) setTimeout(listen, 250);
      else { setVState("idle"); setVReply(t("Toque no círculo quando quiser falar.")); }
    },
    error: (e: any) => {
      const code = e?.error || "";
      if (code === "no-speech" || code === "speech-timeout" || code === "aborted") return;  // o "end" cuida
      // o reconhecimento do celular não funcionou: usa a gravação pelo servidor (como antes)
      sr.current.failed = true; sr.current.on = false;
      if (voiceActive.current) setTimeout(listen, 250);
    },
  };
  useEffect(() => {
    if (!SpeechRec?.addListener) return;
    const subs = ["result", "end", "error"].map((ev) =>
      opt(() => SpeechRec.addListener(ev, (e: any) => srHandlers.current[ev]?.(e))));
    return () => subs.forEach((x: any) => { try { x?.remove(); } catch {} });
  }, []);

  async function listen() {
    if (!voiceActive.current) return;
    if (SpeechRec && !sr.current.failed) {
      try {
        if (!SpeechRec.isRecognitionAvailable || SpeechRec.isRecognitionAvailable()) {
          sr.current.text = ""; sr.current.on = true;
          SpeechRec.start({
            lang: ttsLanguage(), interimResults: true, continuous: false, addsPunctuation: true,
            androidIntentOptions: { EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS: 1200 },
          });
          setVState("listening");
          return;
        }
        sr.current.failed = true;
      } catch { sr.current.failed = true; sr.current.on = false; }
    }
    try {
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await voiceRec.prepareToRecordAsync();
      voiceRec.record();
    } catch (e: any) { setVReply(`${t("Não consegui abrir o microfone")}: ${e?.message ?? e}`); return; }
    setVState("listening");
    const v = vad.current;
    v.t0 = Date.now(); v.samples = []; v.speechAt = 0; v.lastLoud = 0; v.floor = -60;
    clearInterval(v.timer);
    v.timer = setInterval(() => {
      const now = Date.now();
      let db: number | undefined;
      try { db = voiceRec.getStatus()?.metering; } catch {}
      if (typeof db !== "number") return;  // sem medidor: a pessoa toca no círculo para enviar
      if (now - v.t0 < 600) { v.samples.push(db); return; }  // mede o ruído do ambiente (carro, rua)
      if (v.samples.length) { v.floor = v.samples.reduce((a, b) => a + b, 0) / v.samples.length; v.samples = []; }
      const loud = db > Math.max(v.floor + 10, -52);
      if (loud) { if (!v.speechAt) v.speechAt = now; v.lastLoud = now; }
      if (v.speechAt && now - v.lastLoud > 1000 && now - v.speechAt > 400) return finishUtterance();
      if (v.speechAt && now - v.speechAt > 30000) return finishUtterance();
      if (!v.speechAt && now - v.t0 > 20000) { clearInterval(v.timer); voiceRec.stop().catch(() => {}).then(() => listen()); }
    }, 120);
  }

  // se a resposta demorar, avisa que está vendo (para a pessoa não achar que o Fidus travou)
  function startFiller() {
    return setTimeout(() => {
      if (!voiceActive.current) return;
      const keys = ["Um instante.", "Deixa eu ver.", "Já vejo isso."];
      const k = keys[Math.floor(Math.random() * keys.length)];
      const mp3 = phraseAudio.current[`${LANG}|${k}`];
      if (mp3 && playClip(mp3)) return;
      if (Speech && !me?.natural_voice) { try { Speech.speak(t(k), { language: ttsLanguage(), rate: 1.05 }); } catch {} }
    }, 2500);
  }

  async function handleVoiceReply(r: any, heard: string) {
    if (!voiceActive.current) return;
    if (!heard) { speak(t("Não entendi. Pode repetir?"), null, "Não entendi. Pode repetir?"); return; }
    setVHeard(heard);
    if (EXIT_RE.test(heard)) { setVReply(t("Até mais!")); speak(t("Até mais!"), null, "Até mais!"); setTimeout(closeVoice, 1600); return; }
    if (r.cancelled) return;
    showResult(r);  // vai também para a conversa, com cartões de rascunho, documentos etc.
    setVReply(r.reply || "");
    speak(r.speech || r.reply || t("Feito."), r.speech_audio);
  }

  // texto já transcrito no celular: vai direto para o Fidus (sem mandar áudio)
  async function submitVoiceText(text: string) {
    if (!voiceActive.current) return;
    setVState("thinking"); setVHeard(text);
    if (EXIT_RE.test(text)) { setVReply(t("Até mais!")); speak(t("Até mais!"), null, "Até mais!"); setTimeout(closeVoice, 1600); return; }
    push({ id: uid(), type: "user", text });
    const filler = startFiller();
    try {
      const r = await post("/v1/message", { text, mode: "voice", drafts: visibleDrafts(), request_id: uid() });
      clearTimeout(filler);
      if (!voiceActive.current) return;
      if (r.cancelled) return;
      showResult(r, false);
      setVReply(r.reply || "");
      speak(r.speech || r.reply || t("Feito."), r.speech_audio);
    } catch (e: any) {
      clearTimeout(filler);
      setVReply(`${t("Falha de conexão")}: ${e?.message ?? e}`);
      speak(t("Perdi a conexão com o servidor. Tente de novo em instantes."), null, "Perdi a conexão com o servidor. Tente de novo em instantes.");
    }
  }

  async function finishUtterance() {
    clearInterval(vad.current.timer);
    if (!voiceActive.current) return;
    if (sr.current.on) { try { SpeechRec.stop(); } catch {} ; return; }  // o "end" manda o texto
    setVState("thinking");
    try { await voiceRec.stop(); } catch {}
    const uri = voiceRec.uri;
    if (!uri) return listen();
    const filler = startFiller();
    try {
      const audio_b64 = await new File(uri).base64();
      const ext = (uri.match(/\.[a-z0-9]+$/i)?.[0] || ".m4a").toLowerCase();
      const r = await post("/v1/voice_b64", { audio_b64, ext, mode: "voice", drafts: visibleDrafts() });
      clearTimeout(filler);
      await handleVoiceReply(r, r.transcript || "");
    } catch (e: any) {
      clearTimeout(filler);
      setVReply(`${t("Falha de conexão")}: ${e?.message ?? e}`);
      speak(t("Perdi a conexão com o servidor. Tente de novo em instantes."), null, "Perdi a conexão com o servidor. Tente de novo em instantes.");
    }
  }

  function tapVoiceCircle() {
    if (vState === "speaking") { try { Speech?.stop(); } catch {} ; stopClip(); listen(); }
    else if (vState === "listening") finishUtterance();
    else if (vState === "idle" && voiceActive.current) { sr.current.empty = 0; listen(); }
  }

  // ---------- Tarefas ----------
  async function loadTasks() {
    setTasksLoading(true);
    try { setTasks((await api("/v1/tasks", {}, 15000)).tasks || []); }
    catch (e: any) { Alert.alert(t("Tarefas"), errMsg(e)); }
    finally { setTasksLoading(false); }
  }

  async function toggleTask(tk: Task) {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setTasks((prev) => prev.filter((x) => x.id !== tk.id));  // some da lista na hora
    try { await api(`/v1/tasks/${tk.id}/done`, { method: "POST" }); }
    catch (e: any) { Alert.alert(t("Tarefas"), errMsg(e)); loadTasks(); }
  }

  async function addTaskQuick() {
    const title = newTask.trim();
    if (!title) return;
    setNewTask("");
    try { await post("/v1/tasks", { title }); loadTasks(); }
    catch (e: any) { Alert.alert(t("Tarefas"), errMsg(e)); }
  }

  function removeTask(tk: Task) {
    Alert.alert(t("Apagar tarefa?"), tk.title, [
      { text: t("Não"), style: "cancel" },
      { text: t("Apagar"), style: "destructive", onPress: async () => {
          try { await api(`/v1/tasks/${tk.id}`, { method: "DELETE" }); loadTasks(); }
          catch (e: any) { Alert.alert(t("Erro"), errMsg(e)); }
        } },
    ]);
  }

  function undo(a: any) {
    const what: Record<string, string> = {
      expense_added: t("Apagar o gasto \"{0}\"?", a.title), task_added: t("Apagar a tarefa \"{0}\"?", a.title),
      task_done: t("Reabrir a tarefa \"{0}\"?", a.title), document_saved: t("Apagar o documento \"{0}\"?", a.title),
      bill_added: t("Remover a conta fixa \"{0}\" e o aviso mensal?", a.title), reminder_created: t("Apagar o lembrete \"{0}\"?", a.title),
      export_created: t("Apagar o pacote \"{0}\"?", a.title),
    };
    Alert.alert(t("Desfazer?"), what[a.kind] ?? t("Apagar \"{0}\" da sua agenda?", a.title), [
      { text: t("Não"), style: "cancel" },
      { text: t("Desfazer"), style: "destructive", onPress: async () => {
          try { await api(`/v1/activity/${a.id}/undo`, { method: "POST" }); loadActivity(); }
          catch (e: any) { Alert.alert(t("Erro"), errMsg(e)); }
        } },
    ]);
  }

  async function logoutLocal() {
    await SecureStore.deleteItemAsync("token");
    setToken(""); setMe(null); setItems([]); setScreen("chat"); setConfigured(false); setLocked(false);
    setEmailMode(false); setEmailSent(false); setEmailCode("");
  }

  async function logout() {
    kicked.current = true;  // saindo por vontade própria: sem o aviso de "acesso encerrado"
    try { await api("/v1/auth/logout", { method: "POST" }, 8000); } catch { /* sem rede: sai assim mesmo */ }
    await logoutLocal();
  }

  function logoutAll() {
    Alert.alert(t("Sair de todos os aparelhos?"), t("A conta será desconectada em todos os aparelhos, inclusive neste."), [
      { text: t("Cancelar"), style: "cancel" },
      { text: t("Sair de todos"), style: "destructive", onPress: async () => {
          kicked.current = true;
          try { await api("/v1/auth/logout_all", { method: "POST" }, 10000); } catch {}
          await logoutLocal();
        } },
    ]);
  }

  // ---------- Aparelho ----------
  async function deviceInfo() {
    let id = await SecureStore.getItemAsync("deviceId");
    if (!id) { id = randomSecret().slice(0, 32); await SecureStore.setItemAsync("deviceId", id); }
    const model = (Platform as any).constants?.Model || (Platform as any).constants?.model || "";
    return { device_id: id, device_name: `${Platform.OS === "ios" ? "iPhone" : "Android"}${model ? ` · ${model}` : ""}` };
  }

  // ---------- Trava com digital ou rosto ----------
  useEffect(() => {
    (async () => {
      try { setLockAvail(!!LocalAuth && (await LocalAuth.hasHardwareAsync()) && (await LocalAuth.isEnrolledAsync())); } catch { setLockAvail(false); }
      try { setSpeakAudio((await SecureStore.getItemAsync("speakAudio2")) === "1"); } catch {}
      const on = (await SecureStore.getItemAsync("lock")) === "1";
      setLockOn(on);
      if (on) { setLocked(true); unlock(); }
    })();
    const sub = AppState.addEventListener("change", async (st) => {
      if (st === "background") bgAt.current = Date.now();
      if (st === "active" && bgAt.current && Date.now() - bgAt.current > 30000 && (await SecureStore.getItemAsync("lock")) === "1") {
        setLocked(true); unlock();
      }
    });
    return () => sub.remove();
  }, []);

  async function unlock() {
    try {
      const enrolled = await LocalAuth.isEnrolledAsync();
      const r = enrolled ? await LocalAuth.authenticateAsync({ promptMessage: t("Desbloquear o Fidus"), cancelLabel: t("Cancelar") }) : null;
      if (r?.success) return setLocked(false);
      // digital/rosto removidos do celular ou indisponíveis: não prende a pessoa fora do app
      if (!enrolled || ["not_enrolled", "passcode_not_set", "not_available"].includes(r?.error)) {
        await SecureStore.setItemAsync("lock", "0"); setLockOn(false); setLocked(false);
      }
    } catch { setLocked(false); }  // sem o módulo: idem
  }

  async function toggleSpeakAudio() {
    if (!canSpeak) return Alert.alert(t("Responder áudios em voz alta"), t("Instale o APK novo para o Fidus falar."));
    const on = !speakAudio;
    try { await SecureStore.setItemAsync("speakAudio2", on ? "1" : "0"); } catch {}
    setSpeakAudio(on); if (!on) { try { Speech.stop(); } catch {} }
    flash(on ? t("O Fidus vai responder seus áudios falando") : t("Respostas aos áudios só por escrito"));
  }

  // o Fidus consegue falar: voz do celular (expo-speech) ou voz natural do servidor (precisa tocar MP3)
  const canSpeak = !!Speech || (!!me?.natural_voice && !!createPlayer);

  function sayReply(r: any) {  // resposta a um áudio gravado (fora do modo conversa)
    if (!speakAudio || voiceActive.current) return;
    if (r?.speech_audio && playClip(r.speech_audio)) return;
    const text = r?.speech || r?.reply;
    if (!text || !Speech) return;
    try { Speech.stop(); Speech.speak(text, { language: ttsLanguage(), rate: 1.02 }); } catch {}
  }

  async function toggleLock() {
    if (!lockAvail) return Alert.alert(t("Trava"), t("Este celular não tem digital ou rosto cadastrados, ou o app precisa ser atualizado."));
    try {
      const r = await LocalAuth.authenticateAsync({ promptMessage: lockOn ? t("Desligar a trava") : t("Ligar a trava") });
      if (!r?.success) return;
      const on = !lockOn;
      await SecureStore.setItemAsync("lock", on ? "1" : "0");
      setLockOn(on); flash(on ? t("Trava ligada") : t("Trava desligada"));
    } catch (e: any) { Alert.alert(t("Trava"), e?.message ?? String(e)); }
  }

  // ---------- Entrar com Google ----------
  const normServer = () => (server.trim() || DEFAULT_SERVER).replace(/\/$/, "");

  async function loginGoogle() {
    const sv = normServer();
    setServer(sv); await SecureStore.setItemAsync("server", sv);
    const secret = randomSecret();
    await SecureStore.setItemAsync("loginSecret", secret);  // guardado: o app pode ser fechado enquanto o Google abre
    const ref = refCode.trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
    await Linking.openURL(`${sv}/auth/google/login?cc=${sha256hex(secret)}${ref ? `&ref=${ref}` : ""}`);
  }

  async function redeem(code: string) {
    const clean = code.trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (clean.length < 8) return Alert.alert(t("Código"), t("Digite o código de 8 letras que apareceu depois do Google."));
    const sv = normServer();
    setLoggingIn(true);
    try {
      const verifier = await SecureStore.getItemAsync("loginSecret");
      const r = await fetch(`${sv}/v1/auth/exchange`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: clean, verifier, ...(await deviceInfo()) }) });
      if (!r.ok) throw new Error(r.status === 400 ? t("código inválido ou expirado. Entre com o Google de novo.") : `${t("erro")} ${r.status}`);
      const j = await r.json();
      await SecureStore.setItemAsync("server", sv); await SecureStore.setItemAsync("token", j.token);
      await SecureStore.deleteItemAsync("loginSecret");
      setServer(sv); setToken(j.token); setLoginCode(""); kicked.current = false; setConfigured(true);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch (e: any) { Alert.alert(t("Não deu certo"), e?.message ?? String(e)); }
    finally { setLoggingIn(false); }
  }

  // ---------- Entrar com e-mail (código de 6 números) ----------
  async function emailStart() {
    const email = loginEmail.trim().toLowerCase();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return Alert.alert(t("E-mail"), t("Digite um e-mail válido."));
    const sv = normServer();
    setLoggingIn(true);
    try {
      const secret = randomSecret();
      await SecureStore.setItemAsync("loginSecret", secret);
      const ref = refCode.trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
      const r = await fetch(`${sv}/v1/auth/email/start`, { method: "POST", headers: { "Content-Type": "application/json", "Accept-Language": LOCALE },
        body: JSON.stringify({ email, cc: sha256hex(secret), ref }) });
      if (!r.ok) throw new Error(r.status === 429 ? t("Muitos códigos pedidos. Tente mais tarde.") : `${t("erro")} ${r.status}`);
      setEmailSent(true);
    } catch (e: any) { Alert.alert(t("Não deu certo"), e?.message ?? String(e)); }
    finally { setLoggingIn(false); }
  }

  async function emailVerify() {
    const code = emailCode.replace(/\D/g, "");
    if (code.length !== 6) return Alert.alert(t("Código"), t("Digite os 6 números que chegaram no seu e-mail."));
    const sv = normServer();
    setLoggingIn(true);
    try {
      const verifier = await SecureStore.getItemAsync("loginSecret");
      const r = await fetch(`${sv}/v1/auth/email/verify`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: loginEmail.trim().toLowerCase(), code, verifier, ...(await deviceInfo()) }) });
      const j = await r.json();
      if (!r.ok) throw new Error(t(String(j?.detail || r.status)));
      await SecureStore.setItemAsync("server", sv); await SecureStore.setItemAsync("token", j.token);
      await SecureStore.deleteItemAsync("loginSecret");
      setServer(sv); setToken(j.token); setEmailCode(""); setEmailSent(false); setEmailMode(false); kicked.current = false; setConfigured(true);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch (e: any) { Alert.alert(t("Não deu certo"), e?.message ?? String(e)); }
    finally { setLoggingIn(false); }
  }

  // links que abrem o app: fidus://login?code=XXXX (depois do Google) e fidus://invite?code=XXXX (convite)
  useEffect(() => {
    const handle = (url?: string | null) => {
      const m = url && url.match(/login\?code=([A-Za-z0-9-]+)/);
      if (m && !configured) redeem(m[1]);
      const inv = url && url.match(/invite\?code=([A-Za-z0-9]+)/);
      if (inv) { setRefCode(inv[1]); setRefApply(inv[1]); }
    };
    Linking.getInitialURL().then(handle).catch(() => {});
    const sub = Linking.addEventListener("url", (e: any) => handle(e.url));
    return () => sub.remove();
  }, [configured, server]);

  // ---------- Clientes (só o dono) ----------
  async function loadAdmin() {
    setAdminLoading(true);
    try { setAdmin(await api("/v1/admin/users", {}, 20000)); }
    catch (e: any) { Alert.alert(t("Clientes"), errMsg(e)); }
    finally { setAdminLoading(false); }
  }

  async function sendInvite(planId: string) {
    const email = inviteEmail.trim().toLowerCase();
    if (!email.includes("@")) return Alert.alert(t("Convite"), t("Digite o e-mail Google da pessoa."));
    try {
      await post("/v1/admin/invites", { email, plan: planId });
      setInviteEmail(""); loadAdmin();
      Alert.alert(t("Convite criado"), t("{0} já pode entrar com o Google no app (plano {1}).", email, PLAN_NAMES[planId]));
    } catch (e: any) { Alert.alert(t("Convite"), errMsg(e)); }
  }

  function inviteMenu() {
    setSheet({ title: t("Convidar {0} no plano:", inviteEmail.trim() || "…"), items:
      Object.entries(PLAN_NAMES).map(([id, name]) => [t(name), () => sendInvite(id)] as [string, () => void]) });
  }

  function clientMenu(u: any) {
    const act = (path: string, body: any) => async () => {
      try { await post(path, body); loadAdmin(); }
      catch (e: any) { Alert.alert(t("Erro"), errMsg(e)); }
    };
    setSheet({ title: u.email || u.name || u.id, items: [
      ...Object.entries(PLAN_NAMES).filter(([id]) => id !== u.plan)
        .map(([id, name]) => [t("Mudar para {0}", t(name)), act(`/v1/admin/users/${u.id}/plan`, { plan: id })] as [string, () => void]),
      ...(u.is_owner ? [] : [[u.status === "ativo" ? t("Suspender acesso") : t("Reativar acesso"),
        act(`/v1/admin/users/${u.id}/status`, { status: u.status === "ativo" ? "suspenso" : "ativo" })] as [string, () => void]]),
    ] });
  }

  function showResult(res: any, showTranscript = true) {
    histLen.current += 2;  // pedido + resposta
    if (showTranscript && res.transcript) push({ id: uid(), type: "user", text: res.transcript });
    if (res.reply) push({ id: uid(), type: "fidus", text: res.reply });
    for (const a of res.pending_actions || []) push({ id: uid(), type: "action", action: a });
    for (const d of res.documents || []) push({ id: uid(), type: "doc", doc: d });
    if (res.upsell) push({ id: uid(), type: "upsell", up: res.upsell });
    for (const id of res.sent_actions || []) updateAction(id, { status: "sent" });  // "envia" na conversa
    if ((res.sent_actions || []).length) Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
  }

  // ---------- Voz: tocar para gravar, tocar de novo para enviar ----------
  const fail = (msg: string) => push({ id: uid(), type: "fidus", text: `${t("Erro")}: ${msg}` });

  useEffect(() => {  // cronômetro da gravação de voz
    if (!recording) return;
    const t0 = Date.now();
    setRecSecs(0);
    const iv = setInterval(() => setRecSecs(Math.floor((Date.now() - t0) / 1000)), 500);
    return () => clearInterval(iv);
  }, [recording]);

  async function cancelRec() {
    setRecording(false);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try { await recorder.stop(); } catch { /* já parado */ }  // descarta: nada é enviado
  }

  async function toggleRec() {
    if (busy) return;
    if (recording) return stopRec();
    try { Speech?.stop(); } catch {}
    stopClip();
    try {
      const perm = await AudioModule.requestRecordingPermissionsAsync();
      if (!perm.granted) return fail(t("permissão do microfone negada. Libere nas configurações do celular."));
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
      setRecording(true);
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    } catch (e: any) { fail(`${t("ao iniciar gravação")}: ${e?.message ?? e}`); }
  }

  async function stopRec() {
    setRecording(false);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try { await recorder.stop(); } catch (e: any) { return fail(`${t("ao parar gravação")}: ${e?.message ?? e}`); }
    const uri = recorder.uri;
    if (!uri) return fail(t("nenhum áudio foi gravado. Tente de novo."));
    setBusy(true);
    const before = historyCount();
    const rid = uid(); setActiveReq(rid);
    try {
      const audio_b64 = await new File(uri).base64();
      const ext = (uri.match(/\.[a-z0-9]+$/i)?.[0] || ".m4a").toLowerCase();
      const r = await post("/v1/voice_b64", { audio_b64, ext, drafts: visibleDrafts(), speak: canSpeak && speakAudio, request_id: rid });
      if (cancelledReqs.current.has(rid)) return;
      showResult(r);
      sayReply(r);
    } catch (e: any) { if (!cancelledReqs.current.has(rid)) await recover(e, before); }
    finally { if (!cancelledReqs.current.has(rid)) setBusy(false); setActiveReq((x) => (x === rid ? "" : x)); }
  }

  // ---------- Foto: recibo ou documento ----------
  async function pickPhoto(source: "camera" | "library") {
    try {
      const perm = source === "camera"
        ? await ImagePicker.requestCameraPermissionsAsync()
        : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) return fail(t("permissão negada para câmera/galeria."));
      const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 0.5, base64: true };
      const res = source === "camera" ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
      if (res.canceled || !res.assets?.[0]?.base64) return;
      const asset = res.assets[0];
      const note = typed.trim();
      setTyped("");
      push({ id: uid(), type: "user", text: `📷 ${t("Foto enviada")}${note ? `: ${note}` : ""}` });
      setBusy(true);
      const before = historyCount();
      try {
        const media_type = asset.mimeType && ["image/jpeg", "image/png", "image/webp"].includes(asset.mimeType) ? asset.mimeType : "image/jpeg";
        showResult(await post("/v1/photo", { image_b64: asset.base64, media_type, text: note }), false);
      } catch (e: any) { await recover(e, before); }
      finally { setBusy(false); }
    } catch (e: any) { fail(`${t("foto")}: ${e?.message ?? e}`); }
  }

  function photoMenu() {
    setSheet({ title: t("Recibo, fatura, contrato ou documento"), items: [
      [`📷  ${t("Tirar foto")}`, () => pickPhoto("camera")],
      [`🖼  ${t("Escolher da galeria")}`, () => pickPhoto("library")],
      ...(DocumentPicker ? [[`📎  ${t("PDF")}`, pickPdf] as [string, () => void]] : []),
    ] });
  }

  async function pickPdf() {
    try {
      // só PDF: fotos vão pela câmera/galeria, que já reduzem o tamanho
      const res = await DocumentPicker.getDocumentAsync({ type: "application/pdf", copyToCacheDirectory: true });
      if (res.canceled || !res.assets?.[0]) return;
      const a = res.assets[0];
      if ((a.size || 0) > 15 * 1024 * 1024) return fail(t("arquivo grande demais (máx. 15 MB)."));
      const note = typed.trim(); setTyped("");
      push({ id: uid(), type: "user", text: `📎 ${a.name || t("Arquivo")}${note ? `: ${note}` : ""}` });
      setBusy(true);
      const before = historyCount();
      try {
        const image_b64 = await new File(a.uri).base64();
        showResult(await post("/v1/photo", { image_b64, media_type: "application/pdf", text: note }), false);
      } catch (e: any) { await recover(e, before); }
      finally { setBusy(false); }
    } catch (e: any) { fail(`${t("arquivo")}: ${e?.message ?? e}`); }
  }

  async function reconnectGoogle() {
    try { await Linking.openURL((await api("/v1/auth/google/link", {}, 15000)).url); }
    catch (e: any) { Alert.alert("Google", errMsg(e)); }
  }

  async function sendText(preset?: string) {
    const text = (preset ?? typed).trim();
    if (!text) return;
    if (busy) return;
    try { Speech?.stop(); } catch {}
    stopClip();
    if (!preset) setTyped("");
    setBusy(true);
    push({ id: uid(), type: "user", text });  // aparece na hora
    const before = historyCount();
    const rid = uid(); setActiveReq(rid);
    try {
      const r = await post("/v1/message", { text, drafts: visibleDrafts(), request_id: rid });
      if (!cancelledReqs.current.has(rid)) showResult(r, false);
    }
    catch (e: any) { if (!cancelledReqs.current.has(rid)) await recover(e, before); }
    finally { if (!cancelledReqs.current.has(rid)) setBusy(false); setActiveReq((x) => (x === rid ? "" : x)); }
  }

  // botão parar: o Fidus não faz mais nada desse pedido (o que já fez fica na Atividade, com Desfazer)
  function stopRequest() {
    const rid = activeReq;
    if (!rid) return;
    cancelledReqs.current.add(rid);
    post("/v1/cancel", { request_id: rid }, 10000).catch(() => {});
    try { Speech?.stop(); } catch {}
    setActiveReq(""); setBusy(false);
    push({ id: uid(), type: "fidus", text: t("Pedido cancelado. Se algo já tinha sido feito, está na Atividade, com Desfazer.") });
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
  }

  // ---------- Ações que pedem autorização ----------
  function updateAction(id: string, patch: Partial<Action>) {
    setItems((prev) => prev.map((it) =>
      it.type === "action" && it.action.id === id ? { ...it, action: { ...it.action, ...patch } } : it));
  }

  async function confirmInvite(a: Action) {
    Alert.alert(t("Enviar convite?"), `${a.payload.title}\n${t("Para")}: ${(a.payload.emails || []).join(", ")}\n\n${t("O Google manda o convite por e-mail.")}`, [
      { text: t("Cancelar"), style: "cancel" },
      { text: t("Enviar"), onPress: async () => {
          updateAction(a.id, { status: "sending" });  // esconde os botões: um toque = um envio
          try {
            await api(`/v1/actions/${a.id}/confirm`, { method: "POST" });
            updateAction(a.id, { status: "sent" });
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
          } catch (e: any) { updateAction(a.id, { status: "pending" }); Alert.alert(t("Falha ao enviar"), errMsg(e)); }
        } },
    ]);
  }

  async function openDoc(d: Doc) {
    try {
      // o link assinado vale 1 h; se a mensagem for antiga, pede um novo
      const fresh = (await api(`/v1/documents?q=${encodeURIComponent(d.title)}`, {}, 15000)).documents
        ?.find((x: Doc) => x.document_id === d.document_id);
      await Linking.openURL((fresh || d).url);
    } catch (e: any) { Alert.alert(t("Documento"), errMsg(e)); }
  }

  async function saveDraft(a: Action, p: { to: string; subject: string; body: string }) {
    try {
      const r = await post(`/v1/actions/${a.id}/edit`, p, 20000);
      updateAction(a.id, { payload: r.payload });
      flash(t("Rascunho salvo"));
      return true;
    } catch (e: any) { Alert.alert(t("Rascunho"), errMsg(e)); return false; }
  }

  function confirmSend(a: Action) {
    Alert.alert(t("Enviar e-mail?"), `${t("Para")}: ${a.payload.to}\n${a.payload.subject}`, [
      { text: t("Cancelar"), style: "cancel" },
      { text: t("Enviar"), onPress: async () => {
          updateAction(a.id, { status: "sending" });  // esconde os botões: um toque = um envio
          try {
            await api(`/v1/actions/${a.id}/confirm`, { method: "POST" });
            updateAction(a.id, { status: "sent" });
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
          } catch (e: any) { updateAction(a.id, { status: "pending" }); Alert.alert(t("Falha ao enviar"), errMsg(e)); }
        } },
    ]);
  }

  async function cancel(a: Action) {
    try { await api(`/v1/actions/${a.id}/cancel`, { method: "POST" }); updateAction(a.id, { status: "cancelled" }); }
    catch (e: any) { Alert.alert(t("Erro"), errMsg(e)); }
  }

  async function copyText(text: string) {
    try {
      if (Clipboard?.setStringAsync) { await Clipboard.setStringAsync(text); flash(t("Copiado")); return; }
    } catch {}
    try { await Share.share({ message: text }); } catch {}
  }

  // ---------- Menu lateral ----------
  function openDrawer() {
    Keyboard.dismiss();
    setDrawer(true);
    api("/v1/conversations", {}, 15000).then((r) => setConvs(r.conversations || [])).catch(() => {});
    Animated.timing(drawerX, { toValue: 0, duration: 220, easing: Easing.out(Easing.cubic), useNativeDriver: true }).start();
  }
  function closeDrawer(then?: () => void) {
    Animated.timing(drawerX, { toValue: -340, duration: 180, easing: Easing.in(Easing.cubic), useNativeDriver: true })
      .start(() => { setDrawer(false); then?.(); });
  }
  const go = (sc: Screen) => closeDrawer(() => { setScreen(sc); loadScreen(sc); });

  async function loadExpenses(month: string, wallet: string) {
    const q = [month ? `month=${month}` : "", wallet ? `wallet=${encodeURIComponent(wallet)}` : ""].filter(Boolean).join("&");
    setExpenses(await api(`/v1/expenses/summary${q ? `?${q}` : ""}`, {}, 20000));
  }

  function pickWallet(w: string) {
    setExpWallet(w); setExpLock(null);
    loadExpenses(expMonth, w).catch((e: any) => Alert.alert(t("Erro"), errMsg(e)));
  }

  async function saveWallet() {
    const name = (newWallet?.name || "").trim();
    const currency = (newWallet?.currency || "").trim().toUpperCase();
    if (!name) return;
    if (currency && !/^[A-Z]{3}$/.test(currency)) return Alert.alert(t("Carteira"), t("Moeda com 3 letras, ex. GBP, EUR, BRL"));
    try {
      const r = await post("/v1/wallets", { name, currency: currency || null }, 15000);
      if (r.locked) { setExpLock(r); setNewWallet(null); return; }
      setNewWallet(null); flash(t("Carteira salva"));
      await loadExpenses(expMonth, expWallet);
    } catch (e: any) { Alert.alert(t("Carteira"), errMsg(e)); }
  }

  function walletMenu(name: string) {
    Alert.alert(name, t("Remover esta carteira? Os gastos já lançados nela continuam guardados."), [
      { text: t("Cancelar"), style: "cancel" },
      { text: t("Remover"), style: "destructive", onPress: async () => {
        try {
          await post("/v1/wallets/remove", { name }, 15000);
          if (expWallet === name) setExpWallet("");
          await loadExpenses(expMonth, expWallet === name ? "" : expWallet);
        } catch (e: any) { Alert.alert(t("Carteira"), errMsg(e)); }
      } },
    ]);
  }

  async function exportWallet(month: string) {
    try {
      const r = await post("/v1/expenses/export", { month, wallet: expWallet || null }, 60000);
      if (r.locked) return setExpLock(r);
      await Linking.openURL(r.url);
    } catch (e: any) { Alert.alert(t("Contador"), errMsg(e)); }
  }

  async function loadScreen(sc: Screen, arg?: string) {
    if (sc === "tasks") return loadTasks();
    if (sc === "activity") return loadActivity();
    if (sc === "admin") return loadAdmin();
    setLoadingScreen(true);
    try {
      if (sc === "convs") setConvs((await api("/v1/conversations", {}, 15000)).conversations || []);
      if (sc === "docs") setDocs((await api(`/v1/documents${arg ? `?q=${encodeURIComponent(arg)}` : ""}`, {}, 15000)).documents || []);
      if (sc === "meetings") setMeetings(await api("/v1/meetings", {}, 15000));
      if (sc === "expenses") await loadExpenses(arg || "", expWallet);
      if (sc === "booking") setBooking(await api("/v1/booking", {}, 15000));
      if (sc === "invite") setReferral(await api("/v1/referral", {}, 15000));
      if (sc === "settings") {
        setPlan(await api("/v1/plan", {}, 15000));
        const m = await api("/v1/me", {}, 15000); setMe(m); setNameEdit(m.profile?.name || m.name || "");
        setPendingMeet(await SecureStore.getItemAsync("pendingMeeting"));
        try { setDevice(await api("/v1/auth/device", {}, 10000)); } catch {}
      }
    } catch (e: any) { Alert.alert(t("Erro"), errMsg(e)); }
    finally { setLoadingScreen(false); }
  }

  async function newChat() {
    closeDrawer();
    if (busy) return;
    try { await post("/v1/conversations/new", {}, 15000); } catch (e: any) { return Alert.alert(t("Erro"), errMsg(e)); }
    histLen.current = 0;
    setItems([]); setScreen("chat");
  }

  async function openConversation(id: number) {
    closeDrawer();
    try {
      await api(`/v1/conversations/${id}/open`, { method: "POST" }, 15000);
      setItems([]); setScreen("chat");
      await loadHistory();
    } catch (e: any) { Alert.alert(t("Erro"), errMsg(e)); }
  }

  async function openMeeting(m: any) {
    try {
      const st = await api(`/v1/meetings/${m.meeting_id}`, {}, 15000);
      setReader({ title: st.title || m.title || t("Reunião"), text: st.text || st.error || t("Ainda processando…") });
    } catch (e: any) { Alert.alert(t("Reunião"), errMsg(e)); }
  }

  function chooseLanguage() {
    setSheet({ title: t("Idioma do Fidus"), items: LANG_CHOICES.map(([code, label]) => [label, async () => {
      try { await post("/v1/profile", { language: code }); } catch (e: any) { return Alert.alert(t("Erro"), errMsg(e)); }
      await loadLang(code);
      try { await SecureStore.deleteItemAsync("notifV"); setupNotifications(); } catch {}
      loadScreen("settings");
    }] as [string, () => void]) });
  }

  async function saveName() {
    const name = nameEdit.trim();
    if (!name) return;
    try { await post("/v1/profile", { name }); flash(t("Salvo")); loadScreen("settings"); }
    catch (e: any) { Alert.alert(t("Erro"), errMsg(e)); }
  }

  async function sendFeedback(itemId: string, value: number) {
    setFb((p) => ({ ...p, [itemId]: value }));
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    try { await post("/v1/feedback", { value }, 10000); } catch {}
  }

  async function sendNps(itemId: string) {
    if (npsScore == null) return;
    try { await post("/v1/nps", { score: npsScore, comment: npsText.trim() }, 10000); } catch {}
    setItems((prev) => prev.filter((x) => x.id !== itemId));
    setNpsScore(null); setNpsText(""); flash(t("Obrigado!"));
  }

  async function skipNps(itemId: string) {
    setItems((prev) => prev.filter((x) => x.id !== itemId));
    try { await SecureStore.setItemAsync("npsSkip", String(Date.now())); } catch {}
  }

  async function panelCode() {
    try { setPanel(await post("/v1/admin/panel_code", {}, 15000)); }
    catch (e: any) { Alert.alert(t("Painel da empresa"), errMsg(e)); }
  }

  async function exportData() {
    try {
      flash(t("Preparando seus dados…"));
      const r = await api("/v1/account/export", { method: "POST" }, 120000);
      Alert.alert(t("Seus dados"), t("O arquivo com todos os seus dados está pronto. Ele também fica em Documentos."), [
        { text: t("Fechar"), style: "cancel" }, { text: t("Baixar"), onPress: () => Linking.openURL(r.url).catch(() => {}) }]);
    } catch (e: any) { Alert.alert(t("Erro"), errMsg(e)); }
  }

  const [delWord, setDelWord] = useState("");
  const [delOpen, setDelOpen] = useState(false);
  async function deleteAccount() {
    try {
      await post("/v1/account/delete", { confirm: delWord }, 30000);
      setDelOpen(false); setDelWord("");
      Alert.alert(t("Conta apagada"), t("Sua conta foi apagada. Se você tinha assinatura pela Google Play ou App Store, cancele também por lá."));
      kicked.current = true;
      await logoutLocal();
    } catch (e: any) { Alert.alert(t("Erro"), /confirmação/.test(errMsg(e)) ? t("Digite APAGAR para confirmar.") : errMsg(e)); }
  }

  async function shareInvite() {
    if (!referral) return;
    const msg = t("Estou usando o Fidus, um assessor pessoal por voz: agenda, e-mails, gastos e recibos. Com o meu convite você ganha {0} dias grátis: {1} (código {2})",
      referral.trial_days, referral.link, referral.code);
    try { await Share.share({ message: msg }); } catch {}
  }

  async function applyReferral() {
    const code = refApply.trim();
    if (!code) return;
    try { const r = await post("/v1/referral/apply", { code }); setRefApply("");
      Alert.alert(t("Convite"), t("Pronto! Você ganhou {0} dias grátis.", r.trial_days)); loadScreen("invite"); }
    catch (e: any) { Alert.alert(t("Convite"), errMsg(e)); }
  }

  async function subscribe(p: any) {
    const planId = p.plan || p.id;
    if (storeReady) {
      try {
        const off = await Purchases.getOfferings();
        const pkgs = (off?.current?.availablePackages || []).filter((k: any) => String(k.product?.identifier || "").includes(planId));
        if (pkgs.length) {
          const label = (k: any) => `${k.packageType === "ANNUAL" ? t("Anual") : k.packageType === "MONTHLY" ? t("Mensal") : (k.product?.title || "")} · ${k.product?.priceString || ""}`;
          return setSheet({ title: t("Plano {0}", t(p.name)) + (billing?.referral_trial ? ` · ${t("convite: dias grátis")}` : ""),
            items: pkgs.map((k: any) => [label(k), () => buy(k, planId, p.name)] as [string, () => void]) });
        }
      } catch (e: any) { console.log("[Fidus] ofertas", e?.message ?? e); }
    }
    if (plan?.url) Linking.openURL(plan.url);
    else Alert.alert(t("Plano {0}", t(p.name)), t("A assinatura pelo app chega em breve. Por enquanto, fale com a gente pelo e-mail de suporte."));
  }

  const SCREEN_TITLE = (): Record<Screen, string> => ({
    chat: "Fidus", convs: t("Conversas"), tasks: t("Tarefas"), docs: t("Documentos"), meetings: t("Reuniões e atas"),
    expenses: t("Gastos e contas"), booking: t("Link de agendamento"), activity: t("Atividade"),
    invite: t("Convide e ganhe"), admin: t("Clientes"), settings: t("Configurações"), panel: t("Painel da empresa"),
  });

  // ---------- Telas ----------
  if (!configured) {
    return (
      <SafeAreaView edges={["top", "bottom"]} style={[s.flex, { backgroundColor: c.bg }]}>
        <ScrollView contentContainerStyle={s.setup} keyboardShouldPersistTaps="handled">
          <Text style={[s.logo, { color: c.text }]}>Fidus</Text>
          <Text style={{ color: c.sub, marginBottom: 28, fontSize: 16 }}>{t("Fale. O Fidus resolve.")}</Text>
          <Pressable style={[s.primary, { flexDirection: "row", justifyContent: "center", gap: 10 }]} onPress={loginGoogle}>
            <Text style={[s.primaryText, { fontSize: 17 }]}>{t("Entrar com o Google")}</Text></Pressable>
          {authOpts?.email && !emailMode && (
            <Pressable style={[s.secondary, { borderColor: c.sub, alignItems: "center", marginTop: 10, paddingVertical: 14 }]} onPress={() => setEmailMode(true)}>
              <Text style={{ color: c.text, fontSize: 16, fontWeight: "600" }}>{t("Entrar com e-mail")}</Text></Pressable>)}
          {emailMode && (
            <View style={{ marginTop: 14 }}>
              {!emailSent ? (<>
                <TextInput style={[s.input, { color: c.text, backgroundColor: c.card }]} placeholder={t("seu@email.com")} placeholderTextColor={c.sub}
                  autoCapitalize="none" keyboardType="email-address" autoComplete="email" value={loginEmail} onChangeText={setLoginEmail}
                  onSubmitEditing={emailStart} />
                <Pressable style={[s.primary, { opacity: loggingIn ? 0.5 : 1 }]} disabled={loggingIn} onPress={emailStart}>
                  <Text style={s.primaryText}>{loggingIn ? "…" : t("Mandar código")}</Text></Pressable>
              </>) : (<>
                <Text style={{ color: c.sub, marginBottom: 8 }}>{t("Mandamos um código de 6 números para {0}. Ele vale 10 minutos.", loginEmail.trim())}</Text>
                <TextInput style={[s.input, { color: c.text, backgroundColor: c.card, letterSpacing: 8, fontSize: 22, textAlign: "center" }]}
                  placeholder="000000" placeholderTextColor={c.sub} keyboardType="number-pad" maxLength={6} autoComplete="one-time-code"
                  value={emailCode} onChangeText={setEmailCode} onSubmitEditing={emailVerify} />
                <Pressable style={[s.primary, { opacity: loggingIn ? 0.5 : 1 }]} disabled={loggingIn} onPress={emailVerify}>
                  <Text style={s.primaryText}>{loggingIn ? "…" : t("Entrar")}</Text></Pressable>
                <Pressable onPress={() => { setEmailSent(false); setEmailCode(""); }} style={{ marginTop: 10 }}>
                  <Text style={{ color: c.sub, textDecorationLine: "underline" }}>{t("Usar outro e-mail ou mandar de novo")}</Text></Pressable>
              </>)}
            </View>)}
          <Text style={{ color: c.sub, marginTop: 16, marginBottom: 6, fontSize: 13 }}>{t("Tem um código de convite? (opcional)")}</Text>
          <TextInput style={[s.input, { color: c.text, backgroundColor: c.card, letterSpacing: 2 }]}
            placeholder="AB12CD" placeholderTextColor={c.sub} autoCapitalize="characters" autoCorrect={false}
            value={refCode} onChangeText={setRefCode} />
          <Text style={{ color: c.sub, marginTop: 10, marginBottom: 8 }}>{t("Depois do Google, se o app não abrir sozinho, digite o código:")}</Text>
          <View style={[s.row, { gap: 8 }]}>
            <TextInput style={[s.input, s.flex, { color: c.text, backgroundColor: c.card, marginBottom: 0, letterSpacing: 3, fontSize: 18 }]}
              placeholder="ABCD-1234" placeholderTextColor={c.sub} autoCapitalize="characters" autoCorrect={false}
              value={loginCode} onChangeText={setLoginCode} onSubmitEditing={() => redeem(loginCode)} />
            <Pressable style={[s.primarySm, { justifyContent: "center", opacity: loggingIn ? 0.5 : 1 }]} disabled={loggingIn}
              onPress={() => redeem(loginCode)}><Text style={s.primaryText}>{loggingIn ? "…" : t("Entrar")}</Text></Pressable>
          </View>
          <Pressable onPress={() => setShowAdvanced(!showAdvanced)} style={{ marginTop: 28 }}>
            <Text style={{ color: c.sub, textDecorationLine: "underline" }}>{showAdvanced ? t("Fechar opções avançadas") : t("Opções avançadas")}</Text></Pressable>
          {showAdvanced && (<>
            <TextInput style={[s.input, { color: c.text, backgroundColor: c.card, marginTop: 12 }]} placeholder={DEFAULT_SERVER}
              placeholderTextColor={c.sub} autoCapitalize="none" value={server} onChangeText={setServer} />
            <TextInput style={[s.input, { color: c.text, backgroundColor: c.card }]} placeholder={t("Token de administrador")}
              placeholderTextColor={c.sub} autoCapitalize="none" secureTextEntry value={token} onChangeText={setToken} />
            <Pressable style={[s.secondary, { borderColor: c.sub, alignItems: "center" }]} onPress={async () => {
              const sv = normServer(); const tk = token.trim(); if (!tk) return;
              setServer(sv); setToken(tk);
              await SecureStore.setItemAsync("server", sv); await SecureStore.setItemAsync("token", tk);
              kicked.current = false; setConfigured(true);
            }}><Text style={{ color: c.text }}>{t("Entrar com token")}</Text></Pressable>
          </>)}
        </ScrollView>
      </SafeAreaView>
    );
  }

  const Empty = ({ text }: { text: string }) => <Text style={[s.empty, { color: c.sub }]}>{loadingScreen ? t("Carregando…") : text}</Text>;
  const Lock = ({ r }: { r: any }) => r?.locked && r.upsell ? (
    <View style={{ padding: 16, gap: 10 }}>
      <Text style={{ color: c.text }}>{t("{0} faz parte do plano {1}.", t(r.upsell.feature_label), t(r.upsell.name))}</Text>
      <UpsellCard u={r.upsell} />
    </View>) : null;
  const UpsellCard = ({ u, onClose }: { u: Upsell; onClose?: () => void }) => (
    <View style={[s.draft, { backgroundColor: NAVY, borderColor: MINT }]}>
      <Text style={{ color: MINT, fontSize: 12, fontWeight: "700", letterSpacing: 0.5 }}>{t("PLANO {0}", t(u.name).toUpperCase())}</Text>
      <Text style={{ color: "#fff", fontSize: 22, fontWeight: "800", marginTop: 4 }}>{money(u.month, u.symbol)}<Text style={{ fontSize: 13, fontWeight: "400", color: "#B9C6DD" }}> {t("/mês · ou {0}/ano", money(u.year, u.symbol))}</Text></Text>
      <Text style={{ color: "#DDE5F2", marginTop: 6 }}>{t("Libera {0} e mais:", t(u.feature_label))}</Text>
      {u.highlights.slice(0, 4).map((h) => <Text key={h} style={{ color: "#fff", marginTop: 3 }}>✓ {t(h)}</Text>)}
      <View style={[s.row, { marginTop: 12 }]}>
        {onClose && <Pressable style={[s.secondary, { borderColor: "#5B6B85" }]} onPress={onClose}>
          <Text style={{ color: "#DDE5F2" }}>{t("Agora não")}</Text></Pressable>}
        <Pressable style={[s.primarySm, { backgroundColor: MINT }]} onPress={() => subscribe(u)}>
          <Text style={{ color: NAVY, fontWeight: "700" }}>{t("Conhecer o {0}", t(u.name))}</Text></Pressable>
      </View>
    </View>);

  const sumLine = (byCur: Record<string, number>) => Object.entries(byCur || {}).map(([cur, v]) => `${v.toFixed(2)} ${cur}`).join(" · ");
  const shiftMonth = (m: string, d: number) => { if (!/^\d{4}-\d{2}$/.test(m)) return ""; const [y, mm] = m.split("-").map(Number); const x = new Date(y, mm - 1 + d, 1);
    return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}`; };

  function renderScreen() {
    if (screen === "admin") return (
      <FlatList
        data={admin.users} keyExtractor={(u) => u.id} contentContainerStyle={{ padding: 16, gap: 8 }}
        refreshing={adminLoading} onRefresh={loadAdmin}
        ListHeaderComponent={
          <View style={{ gap: 8, marginBottom: 8 }}>
            <View style={[s.row, { gap: 8 }]}>
              <TextInput style={[s.input, s.flex, { color: c.text, backgroundColor: c.card, marginBottom: 0 }]}
                placeholder={t("E-mail Google para convidar")} placeholderTextColor={c.sub} autoCapitalize="none"
                keyboardType="email-address" value={inviteEmail} onChangeText={setInviteEmail} />
              <Pressable onPress={inviteMenu} style={[s.primarySm, { justifyContent: "center" }]}>
                <Text style={s.primaryText}>{t("Convidar")}</Text></Pressable>
            </View>
            <Text style={{ color: c.sub, fontSize: 14 }}>
              {t("{0} conta(s) · {1} convite(s) aguardando", admin.users.length, admin.invites.filter((i: any) => !i.used_at).length)}
            </Text>
            {admin.invites.filter((i: any) => !i.used_at).map((i: any) => (
              <Text key={i.email} style={{ color: c.sub, fontSize: 14 }}>✉️ {i.email} · {t(PLAN_NAMES[i.plan] ?? i.plan)}</Text>
            ))}
          </View>}
        renderItem={({ item: u }) => (
          <Pressable onPress={() => clientMenu(u)} style={[s.actCard, { backgroundColor: c.card, opacity: u.status === "ativo" ? 1 : 0.5 }]}>
            <View style={{ flex: 1 }}>
              <Text style={{ color: c.text, fontWeight: "700" }}>{u.name || u.email}{u.is_owner ? ` (${t("você")})` : ""}</Text>
              <Text style={{ color: c.sub, fontSize: 14 }}>{u.email}</Text>
              <Text style={{ color: c.sub, fontSize: 12, marginTop: 2 }}>
                {t(PLAN_NAMES[u.plan] ?? u.plan)} · {t("{0} ações no mês", u.actions_this_month)} · {u.google_connected ? t("Google ok") : t("sem Google")}
                {typeof u.ai_cost_month_usd === "number" ? ` · ${t("IA")} $${u.ai_cost_month_usd.toFixed(2)}` : ""}
                {u.device_switches_30d > 2 ? ` · ⚠️ ${t("{0} trocas de aparelho", u.device_switches_30d)}` : ""}
                {u.status !== "ativo" ? ` · ${t("SUSPENSO")}` : ""}</Text>
            </View>
            <Text style={{ color: c.sub }}>›</Text>
          </Pressable>
        )}
      />
    );
    if (screen === "tasks") return (
      <View style={s.flex}>
        <View style={[s.row, { paddingHorizontal: 16, paddingTop: 12, gap: 8 }]}>
          <TextInput style={[s.input, s.flex, { color: c.text, backgroundColor: c.card, marginBottom: 0 }]}
            placeholder={t("Nova tarefa…")} placeholderTextColor={c.sub} value={newTask} onChangeText={setNewTask}
            onSubmitEditing={addTaskQuick} returnKeyType="done" />
          <Pressable onPress={addTaskQuick} style={[s.sendBtn2, { backgroundColor: NAVY, width: 48, height: 48, borderRadius: 24 }]}>
            <PlusIcon color="#fff" /></Pressable>
        </View>
        <FlatList
          data={tasks} keyExtractor={(x) => String(x.id)} contentContainerStyle={{ padding: 16, gap: 8 }}
          refreshing={tasksLoading} onRefresh={loadTasks}
          ListEmptyComponent={<Text style={[s.empty, { color: c.sub }]}>
            {tasksLoading ? t("Carregando…") : t("Nenhuma tarefa aberta.\nDiga, por exemplo: “cria a tarefa de revisar o contrato até sexta”.")}</Text>}
          renderItem={({ item: tk }) => (
            <Pressable onLongPress={() => removeTask(tk)} style={[s.actCard, { backgroundColor: c.card, paddingVertical: 12 }]}>
              <Pressable onPress={() => toggleTask(tk)} hitSlop={10}
                style={[s.check, { borderColor: tk.priority === "alta" ? RED : c.sub }]} accessibilityLabel={t("Concluir")} />
              <View style={{ flex: 1 }}>
                <Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{tk.title}</Text>
                {(!!tk.due || tk.priority === "alta") && (
                  <Text style={{ color: tk.overdue ? RED : c.sub, fontSize: 12, marginTop: 2 }}>
                    {tk.due ? (tk.overdue ? t("atrasada · era {0}", fmtDay(tk.due)) : t("até {0}", fmtDay(tk.due))) : ""}
                    {tk.priority === "alta" ? `${tk.due ? " · " : ""}${t("prioridade alta")}` : ""}</Text>)}
              </View>
            </Pressable>
          )}
        />
      </View>
    );
    if (screen === "activity") return (
      <FlatList
        data={acts} keyExtractor={(a) => String(a.id)} contentContainerStyle={{ padding: 16, gap: 10 }}
        refreshing={actsLoading} onRefresh={loadActivity}
        ListHeaderComponent={stats && stats.actions_this_month > 0 ? (
          <View style={[s.statCard, { backgroundColor: NAVY }]}>
            <Text style={{ color: MINT, fontSize: 28, fontWeight: "800" }}>{stats.actions_this_month}</Text>
            <Text style={{ color: "#fff", flex: 1 }}>{t("coisas que o Fidus resolveu por você este mês")}{"\n"}
              <Text style={{ color: "#B9C6DD", fontSize: 12 }}>≈ {stats.minutes_saved_estimate >= 60
                ? `${Math.round(stats.minutes_saved_estimate / 6) / 10} h` : `${stats.minutes_saved_estimate} min`} {t("poupados (estimativa)")}</Text></Text>
          </View>) : null}
        ListEmptyComponent={<Text style={[s.empty, { color: c.sub }]}>
          {actsLoading ? t("Carregando…") : t("Nada por aqui ainda.\nTudo o que o Fidus fizer por você aparece nesta lista.")}</Text>}
        renderItem={({ item: a }) => {
          const p = pill(a.kind, a.status);
          const faded = a.status === "desfeito" || a.status === "cancelado";
          return (
            <View style={[s.actCard, { backgroundColor: c.card, opacity: faded ? 0.55 : 1 }]}>
              <Text style={s.actIcon}>{ICON[a.kind] ?? "•"}</Text>
              <View style={{ flex: 1 }}>
                <View style={[s.pill, { backgroundColor: p.color + "22", borderColor: p.color }]}>
                  <Text style={{ color: p.color, fontSize: 11, fontWeight: "700" }}>{p.text.toUpperCase()}</Text>
                </View>
                <Text style={{ color: c.text, fontWeight: "600", textDecorationLine: faded || a.kind.endsWith("_deleted") ? "line-through" : "none" }}>{a.title}</Text>
                {!!a.detail && <Text style={{ color: c.sub }}>{a.detail}</Text>}
                <Text style={{ color: c.sub, fontSize: 12, marginTop: 2 }}>{LABEL()[a.kind] ?? a.kind} · {fmtDate(a.created_at)}</Text>
              </View>
              {a.can_undo && (
                <Pressable style={[s.chip, { borderColor: c.sub }]} onPress={() => undo(a)}>
                  <Text style={{ color: c.text, fontSize: 12 }}>{t("Desfazer")}</Text></Pressable>
              )}
            </View>
          );
        }}
      />
    );
    if (screen === "convs") return (
      <FlatList data={convs} keyExtractor={(x) => String(x.id)} contentContainerStyle={{ padding: 16, gap: 8 }}
        refreshing={loadingScreen} onRefresh={() => loadScreen("convs")}
        ListEmptyComponent={<Empty text={t("Nenhuma conversa ainda.")} />}
        renderItem={({ item: cv }) => (
          <Card c={c} onPress={() => openConversation(cv.id)}>
            <View style={{ flex: 1 }}>
              <Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }} numberOfLines={1}>{cv.title === "Conversa" ? t("Conversa") : cv.title}</Text>
              <Text style={{ color: c.sub, fontSize: 12, marginTop: 2 }}>{fmtDate(cv.last)} · {t("{0} mensagens", cv.messages)}</Text>
            </View>
            <Text style={{ color: c.sub }}>›</Text>
          </Card>)} />
    );
    if (screen === "docs") return (
      <View style={s.flex}>
        <View style={{ paddingHorizontal: 16, paddingTop: 12 }}>
          <TextInput style={[s.input, { color: c.text, backgroundColor: c.card, marginBottom: 0 }]} placeholder={t("Buscar documento…")}
            placeholderTextColor={c.sub} value={docQuery} onChangeText={setDocQuery} returnKeyType="search"
            onSubmitEditing={() => loadScreen("docs", docQuery.trim())} />
        </View>
        <FlatList data={docs} keyExtractor={(d) => String(d.document_id)} contentContainerStyle={{ padding: 16, gap: 8 }}
          refreshing={loadingScreen} onRefresh={() => loadScreen("docs", docQuery.trim())}
          ListEmptyComponent={<Empty text={t("Nenhum documento guardado.\nMande a foto de um seguro, contrato ou carta e o Fidus guarda aqui.")} />}
          renderItem={({ item: d }) => (
            <Card c={c} onPress={() => openDoc(d)}>
              <Text style={s.actIcon}>📄</Text>
              <View style={{ flex: 1 }}>
                <Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{d.title}</Text>
                {!!d.expires_on && <Text style={{ color: c.sub, fontSize: 12 }}>{t("vence {0}", `${fmtDay(d.expires_on)}/${d.expires_on.slice(0, 4)}`)}</Text>}
              </View>
              <Text style={{ color: MINT, fontWeight: "700" }}>{t("Abrir")}</Text>
            </Card>)} />
      </View>
    );
    if (screen === "meetings") return meetings?.locked ? <ScrollView><Lock r={meetings} /></ScrollView> : (
      <FlatList data={meetings?.meetings || []} keyExtractor={(m) => String(m.meeting_id)} contentContainerStyle={{ padding: 16, gap: 8 }}
        refreshing={loadingScreen} onRefresh={() => loadScreen("meetings")}
        ListHeaderComponent={<Pressable onPress={() => { setScreen("chat"); meetingMenu(); }} style={[s.primary, { marginBottom: 8 }]}>
          <Text style={s.primaryText}>🎙 {t("Gravar reunião agora")}</Text></Pressable>}
        ListEmptyComponent={<Empty text={t("Nenhuma reunião gravada ainda.")} />}
        renderItem={({ item: m }) => (
          <Card c={c} onPress={() => openMeeting(m)}>
            <Text style={s.actIcon}>🎙</Text>
            <View style={{ flex: 1 }}>
              <Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{m.title || t("Reunião")}</Text>
              <Text style={{ color: c.sub, fontSize: 12 }}>{fmtDay(m.date)}/{(m.date || "").slice(0, 4)} · {m.status === "pronta" ? t("ata pronta") : m.status === "erro" ? t("erro") : t("processando")}</Text>
            </View>
            <Text style={{ color: c.sub }}>›</Text>
          </Card>)} />
    );
    if (screen === "expenses") {
      const e = expenses;
      const month = e?.month || expMonth;
      return (
        <ScrollView contentContainerStyle={{ padding: 16, gap: 10 }}>
          <View style={[s.actCard, { backgroundColor: NAVY, justifyContent: "space-between" }]}>
            <Pressable hitSlop={10} onPress={() => { const m = shiftMonth(month, -1); setExpMonth(m); loadScreen("expenses", m); }}>
              <Text style={{ color: "#fff", fontSize: 22 }}>‹</Text></Pressable>
            <View style={{ alignItems: "center" }}>
              <Text style={{ color: "#B9C6DD", fontSize: 12 }}>{month ? `${month.slice(5)}/${month.slice(0, 4)}` : ""}</Text>
              <Text style={{ color: "#fff", fontSize: 20, fontWeight: "800" }}>{e ? (sumLine(e.totals_by_currency) || "0.00") : "…"}</Text>
              <Text style={{ color: "#B9C6DD", fontSize: 12 }}>{e ? t("{0} lançamentos", e.count) : ""}</Text>
            </View>
            <Pressable hitSlop={10} onPress={() => { const m = shiftMonth(month, 1); setExpMonth(m); loadScreen("expenses", m); }}>
              <Text style={{ color: "#fff", fontSize: 22 }}>›</Text></Pressable>
          </View>
          {!!e?.wallets && (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingVertical: 2 }}>
              {[{ name: "", label: t("Todas") }, ...e.wallets.map((w: any) => ({ name: w.name, label: w.currency ? `${w.name} · ${w.currency}` : w.name, archived: w.archived }))]
                .map((w: any) => {
                  const on = expWallet === w.name;
                  return (
                    <Pressable key={w.name || "_all"} onPress={() => pickWallet(w.name)} onLongPress={() => w.name && !w.archived && walletMenu(w.name)}
                      style={[s.chip, { paddingVertical: 8, paddingHorizontal: 14, borderColor: on ? NAVY : c.line, backgroundColor: on ? NAVY : c.card }]}>
                      <Text style={{ color: on ? "#fff" : c.text, fontSize: 15, fontWeight: on ? "700" : "400" }}>{w.label}</Text>
                    </Pressable>);
                })}
              <Pressable onPress={() => setNewWallet({ name: "", currency: "" })} accessibilityLabel={t("Nova carteira")}
                style={[s.chip, { paddingVertical: 8, paddingHorizontal: 14, borderColor: c.line, borderStyle: "dashed" }]}>
                <Text style={{ color: c.sub, fontSize: 15 }}>+ {t("Carteira")}</Text></Pressable>
            </ScrollView>)}
          {!!newWallet && (
            <Card c={c} style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
              <Text style={{ color: c.sub, fontSize: 14 }}>{t("NOVA CARTEIRA")}</Text>
              <TextInput value={newWallet.name} onChangeText={(v) => setNewWallet({ ...newWallet, name: v })} placeholder={t("Nome, ex. Pessoal BR")}
                placeholderTextColor={c.sub} maxLength={40} style={[s.input, { color: c.text, backgroundColor: c.bg, marginBottom: 0 }]} />
              <TextInput value={newWallet.currency} onChangeText={(v) => setNewWallet({ ...newWallet, currency: v.toUpperCase() })} placeholder={t("Moeda, ex. BRL")}
                placeholderTextColor={c.sub} maxLength={3} autoCapitalize="characters" style={[s.input, { color: c.text, backgroundColor: c.bg, marginBottom: 0 }]} />
              <View style={[s.row, { gap: 8 }]}>
                <Pressable style={[s.secondary, { borderColor: c.line, flex: 1, alignItems: "center" }]} onPress={() => setNewWallet(null)}>
                  <Text style={{ color: c.text }}>{t("Cancelar")}</Text></Pressable>
                <Pressable style={[s.primary, { flex: 1, padding: 10 }]} onPress={saveWallet}>
                  <Text style={s.primaryText}>{t("Salvar")}</Text></Pressable>
              </View>
            </Card>)}
          <Lock r={expLock} />
          {!!e && !expWallet && (e.wallets || []).filter((w: any) => Object.keys(w.totals || {}).length).length > 1 && (
            <Card c={c} style={{ flexDirection: "column", alignItems: "stretch" }}>
              <Text style={{ color: c.sub, fontSize: 12, marginBottom: 4 }}>{t("POR CARTEIRA")}</Text>
              {e.wallets.filter((w: any) => Object.keys(w.totals || {}).length).map((w: any) => (
                <Pressable key={w.name} onPress={() => pickWallet(w.name)} style={s.kv}>
                  <Text style={{ color: c.text }}>{w.name} ›</Text><Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{sumLine(w.totals)}</Text></Pressable>))}
            </Card>)}
          {!!e && Object.keys(e.by_category || {}).length > 0 && (
            <Card c={c} style={{ flexDirection: "column", alignItems: "stretch" }}>
              <Text style={{ color: c.sub, fontSize: 12, marginBottom: 4 }}>{t("POR CATEGORIA")}</Text>
              {Object.entries(e.by_category).map(([k, v]: any) => (
                <View key={k} style={s.kv}><Text style={{ color: c.text }}>{t(k)}</Text><Text style={{ color: c.text }}>{sumLine(v)}</Text></View>))}
            </Card>)}
          {!!e?.recent?.length && (
            <Card c={c} style={{ flexDirection: "column", alignItems: "stretch" }}>
              <Text style={{ color: c.sub, fontSize: 12, marginBottom: 4 }}>{t("ÚLTIMOS LANÇAMENTOS")}</Text>
              {e.recent.map((r: any) => (
                <View key={r.id} style={s.kv}>
                  <Text style={{ color: c.text, flex: 1, fontSize: 15 }} numberOfLines={1}>{fmtDay(r.date)} · {r.merchant || t(r.category)} · {r.business}</Text>
                  <Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{r.amount.toFixed(2)} {r.currency}</Text></View>))}
            </Card>)}
          {!!e?.bills?.length && (
            <Card c={c} style={{ flexDirection: "column", alignItems: "stretch" }}>
              <Text style={{ color: c.sub, fontSize: 12, marginBottom: 4 }}>{t("CONTAS FIXAS")}</Text>
              {e.bills.map((b: any) => (
                <View key={b.bill_id} style={s.kv}>
                  <Text style={{ color: c.text, flex: 1, fontSize: 15 }}>{b.name} · {t("dia {0}", b.day_of_month)}</Text>
                  <Text style={{ color: c.text }}>{b.amount != null ? `${Number(b.amount).toFixed(2)} ${b.currency || ""}` : ""}</Text></View>))}
            </Card>)}
          {!!e && !e.count && !e.bills?.length && <Empty text={t("Nenhum gasto neste mês.\nDiga “paguei 30 libras de gasolina” ou mande a foto do recibo.")} />}
          {!!e?.count && (
            <Pressable style={[s.secondary, { borderColor: c.line, alignItems: "center" }]} onPress={() => exportWallet(month)}>
              <Text style={{ color: c.text }}>📦 {expWallet ? t("Exportar {0} para o contador", expWallet) : t("Exportar o mês para o contador")}</Text></Pressable>)}
          {!!e?.wallets && <Text style={{ color: c.sub, fontSize: 12, textAlign: "center" }}>{t("Toque e segure uma carteira para remover.")}</Text>}
        </ScrollView>
      );
    }
    if (screen === "booking") return booking?.locked ? <ScrollView><Lock r={booking} /></ScrollView> : (
      <ScrollView contentContainerStyle={{ padding: 16, gap: 10 }}>
        {loadingScreen && !booking ? <Empty text="" /> : booking && (<>
          <Text style={{ color: c.sub }}>{t("Mande este link para clientes marcarem horário direto na sua agenda, só nos horários livres.")}</Text>
          <Card c={c} style={{ flexDirection: "column", alignItems: "stretch", gap: 10 }}>
            <Text selectable style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{booking.link}</Text>
            <View style={[s.row, { justifyContent: "flex-start", flexWrap: "wrap" }]}>
              <Pressable style={[s.secondary, { borderColor: c.sub }]} onPress={() => copyText(booking.link)}><Text style={{ color: c.text }}>{t("Copiar")}</Text></Pressable>
              <Pressable style={[s.secondary, { borderColor: c.sub }]} onPress={() => Share.share({ message: booking.link })}><Text style={{ color: c.text }}>{t("Compartilhar")}</Text></Pressable>
              <Pressable style={[s.secondary, { borderColor: c.sub }]} onPress={() => Linking.openURL(booking.link)}><Text style={{ color: c.text }}>{t("Abrir")}</Text></Pressable>
            </View>
          </Card>
          <Card c={c} style={{ flexDirection: "column", alignItems: "stretch" }}>
            <View style={s.kv}><Text style={{ color: c.sub }}>{t("Dias")}</Text><Text style={{ color: c.text }}>{booking.days}</Text></View>
            <View style={s.kv}><Text style={{ color: c.sub }}>{t("Horário")}</Text><Text style={{ color: c.text }}>{booking.hours}</Text></View>
            <View style={s.kv}><Text style={{ color: c.sub }}>{t("Antecedência")}</Text><Text style={{ color: c.text }}>{booking.min_notice_hours} h</Text></View>
            {(booking.types || []).map((x: string) => <Text key={x} style={{ color: c.text, marginTop: 4 }}>• {x}</Text>)}
          </Card>
          <Text style={{ color: c.sub, fontSize: 14 }}>{t("Para mudar dias, horários ou tipos de atendimento, peça ao Fidus na conversa.")}</Text>
        </>)}
      </ScrollView>
    );
    if (screen === "invite") return (
      <ScrollView contentContainerStyle={{ padding: 16, gap: 12 }}>
        <View style={[s.draft, { backgroundColor: NAVY, borderColor: MINT }]}>
          <Text style={{ color: MINT, fontWeight: "800", fontSize: 13 }}>{t("CONVIDE E GANHE")}</Text>
          <Text style={{ color: "#fff", fontSize: 20, fontWeight: "800", marginTop: 6 }}>
            {t("{0}% de desconto na sua próxima cobrança", referral?.percent ?? 10)}</Text>
          <Text style={{ color: "#DDE5F2", marginTop: 6 }}>
            {t("Para cada amigo que assinar o Fidus. Seu amigo ganha {0} dias grátis.", referral?.trial_days ?? 7)}</Text>
          {!!referral && (<>
            <Text selectable style={{ color: "#fff", fontSize: 28, fontWeight: "800", letterSpacing: 4, marginTop: 14 }}>{referral.code}</Text>
            <Text selectable style={{ color: "#B9C6DD", fontSize: 12 }}>{referral.link}</Text>
            <View style={[s.row, { marginTop: 12, justifyContent: "flex-start" }]}>
              <Pressable style={[s.primarySm, { backgroundColor: MINT }]} onPress={shareInvite}>
                <Text style={{ color: NAVY, fontWeight: "700" }}>{t("Enviar convite")}</Text></Pressable>
              <Pressable style={[s.secondary, { borderColor: "#5B6B85" }]} onPress={() => copyText(referral.link)}>
                <Text style={{ color: "#DDE5F2" }}>{t("Copiar link")}</Text></Pressable>
            </View>
          </>)}
        </View>
        {!!referral && (
          <Card c={c} style={{ flexDirection: "column", alignItems: "stretch" }}>
            <View style={s.kv}><Text style={{ color: c.sub }}>{t("Amigos convidados")}</Text><Text style={{ color: c.text, fontWeight: "700" }}>{referral.invited}</Text></View>
            <View style={s.kv}><Text style={{ color: c.sub }}>{t("Já assinaram")}</Text><Text style={{ color: c.text, fontWeight: "700" }}>{referral.paid}</Text></View>
            <View style={s.kv}><Text style={{ color: c.sub }}>{t("Descontos guardados")}</Text><Text style={{ color: c.text, fontWeight: "700" }}>{referral.credits_available}</Text></View>
            <View style={s.kv}><Text style={{ color: c.sub }}>{t("Próxima cobrança")}</Text>
              <Text style={{ color: referral.next_discount ? GREEN : c.text, fontWeight: "700" }}>{referral.next_discount ? `-${referral.next_discount}%` : t("sem desconto")}</Text></View>
          </Card>)}
        <Text style={{ color: c.sub, fontSize: 13, lineHeight: 19 }}>
          {t("Como funciona: o desconto entra quando o amigo paga o primeiro mês. Os descontos não somam: vale um por cobrança, e os que sobram ficam para as cobranças seguintes.")}</Text>
        {!!referral && !referral.invited_by && (
          <Card c={c} style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
            <Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{t("Alguém te convidou?")}</Text>
            <View style={[s.row, { gap: 8 }]}>
              <TextInput style={[s.input, s.flex, { color: c.text, backgroundColor: c.bg, marginBottom: 0 }]} placeholder="AB12CD"
                placeholderTextColor={c.sub} autoCapitalize="characters" value={refApply} onChangeText={setRefApply} />
              <Pressable style={[s.primarySm, { justifyContent: "center" }]} onPress={applyReferral}><Text style={s.primaryText}>{t("Usar")}</Text></Pressable>
            </View>
          </Card>)}
        {!!referral?.invited_by && <Text style={{ color: c.sub }}>{t("Você entrou pelo convite de {0} 🎁", referral.invited_by)}</Text>}
      </ScrollView>
    );
    if (screen === "panel") return (
      <ScrollView contentContainerStyle={{ padding: 16, gap: 12 }}>
        <Text style={{ color: c.sub, lineHeight: 20 }}>{t("O painel mostra a saúde do sistema, o uso do Fidus (HEART), o negócio e a equipe. Abra no computador e digite o código.")}</Text>
        <Pressable style={s.primary} onPress={panelCode}><Text style={s.primaryText}>{t("Gerar código de acesso")}</Text></Pressable>
        {!!panel && (
          <Card c={c} style={{ flexDirection: "column", alignItems: "center", gap: 8 }}>
            <Text selectable style={{ color: c.text, fontSize: 34, fontWeight: "800", letterSpacing: 6 }}>{panel.code}</Text>
            <Text style={{ color: c.sub, fontSize: 14 }}>{t("Vale 5 minutos e só uma vez.")}</Text>
            <Text selectable style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{panel.url}</Text>
            <View style={[s.row, { justifyContent: "center", flexWrap: "wrap" }]}>
              <Pressable style={[s.secondary, { borderColor: c.sub }]} onPress={() => copyText(panel.url)}><Text style={{ color: c.text }}>{t("Copiar endereço")}</Text></Pressable>
              <Pressable style={[s.secondary, { borderColor: c.sub }]} onPress={() => Linking.openURL(panel.url).catch(() => {})}><Text style={{ color: c.text }}>{t("Abrir aqui")}</Text></Pressable>
            </View>
          </Card>)}
      </ScrollView>
    );
    if (screen === "settings") return (
      <ScrollView contentContainerStyle={{ padding: 16, gap: 12 }}>
        <Card c={c} style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
          <Text style={{ color: c.sub, fontSize: 12 }}>{t("SEU NOME")}</Text>
          <View style={[s.row, { gap: 8 }]}>
            <TextInput style={[s.input, s.flex, { color: c.text, backgroundColor: c.bg, marginBottom: 0 }]} value={nameEdit} onChangeText={setNameEdit} />
            <Pressable style={[s.primarySm, { justifyContent: "center" }]} onPress={saveName}><Text style={s.primaryText}>{t("Salvar")}</Text></Pressable>
          </View>
          <Text style={{ color: c.sub, fontSize: 14 }}>{me?.email}</Text>
        </Card>
        <Card c={c} onPress={chooseLanguage}>
          <View style={{ flex: 1 }}><Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{t("Idioma")}</Text>
            <Text style={{ color: c.sub, fontSize: 14 }}>{(LANG_CHOICES.find(([k]) => k === LANG) || [LANG, LANG])[1]}</Text></View>
          <Text style={{ color: c.sub }}>›</Text></Card>
        <Card c={c} style={{ flexDirection: "column", alignItems: "stretch", gap: 10 }}>
          <Text style={{ color: c.sub, fontSize: 12 }}>{t("SEU PLANO")}</Text>
          <Text style={{ color: c.text, fontSize: 18, fontWeight: "800" }}>{plan ? t(plan.name) : "…"}</Text>
          {(plan?.plans || []).map((p: any) => (
            <View key={p.id} style={[s.planRow, { borderColor: p.id === plan.plan ? MINT : c.line }]}>
              <View style={{ flex: 1 }}>
                <Text style={{ color: c.text, fontWeight: "700" }}>{t(p.name)} · {money(p.month, plan.symbol)}<Text style={{ color: c.sub, fontWeight: "400" }}>{t("/mês")}</Text></Text>
                <Text style={{ color: c.sub, fontSize: 12 }}>{t("ou {0}/ano (2 meses grátis)", money(p.year, plan.symbol))}</Text>
                {p.highlights.slice(0, 3).map((h: string) => <Text key={h} style={{ color: c.sub, fontSize: 12 }}>✓ {t(h)}</Text>)}
              </View>
              {p.id === plan.plan ? <Text style={{ color: GREEN, fontWeight: "700" }}>{t("Atual")}</Text> :
                <Pressable style={[s.chip, { borderColor: c.sub }]} onPress={() => subscribe(p)}><Text style={{ color: c.text }}>{t("Escolher")}</Text></Pressable>}
            </View>))}
        </Card>
        {storeReady && (<>
          <Card c={c} onPress={() => Linking.openURL(MANAGE_SUBS_URL).catch(() => {})}>
            <View style={{ flex: 1 }}><Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{t("Gerenciar assinatura")}</Text>
              <Text style={{ color: c.sub, fontSize: 14 }}>{t("Trocar forma de pagamento ou cancelar, direto na loja")}</Text></View>
            <Text style={{ color: c.sub }}>›</Text></Card>
          <Card c={c} onPress={restorePurchases}><Text style={{ color: c.text, flex: 1, fontSize: 15 }}>{t("Restaurar compras")}</Text></Card>
        </>)}
        {!!me?.natural_voice && (
          <Card c={c} onPress={async () => {
            const g = me.voice_gender === "male" ? "female" : "male";
            try { await post("/v1/profile", { voice_gender: g }); setMe({ ...me, voice_gender: g }); phraseAudio.current = {}; preloadPhrases();
              flash(g === "male" ? t("Voz masculina") : t("Voz feminina")); } catch (e: any) { Alert.alert(t("Erro"), errMsg(e)); }
          }}>
            <View style={{ flex: 1 }}><Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{t("Voz do Fidus")}</Text>
              <Text style={{ color: c.sub, fontSize: 14 }}>{t("Toque para trocar")}</Text></View>
            <Text style={{ color: c.text, fontWeight: "700" }}>{me.voice_gender === "male" ? t("Masculina") : t("Feminina")}</Text></Card>)}
        <Card c={c} onPress={toggleSpeakAudio}>
          <View style={{ flex: 1 }}><Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{t("Responder áudios em voz alta")}</Text>
            <Text style={{ color: c.sub, fontSize: 14 }}>{!canSpeak ? t("Disponível no app atualizado") : speakAudio ? t("Ligado: quando você manda áudio, o Fidus responde falando") : t("Desligado: respostas só por escrito")}</Text></View>
          <Text style={{ color: speakAudio && canSpeak ? GREEN : c.sub, fontWeight: "700" }}>{speakAudio && canSpeak ? t("Ligado") : t("Ligar")}</Text></Card>
        <Card c={c} onPress={toggleLock}>
          <View style={{ flex: 1 }}><Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{t("Trava com digital ou rosto")}</Text>
            <Text style={{ color: c.sub, fontSize: 14 }}>{lockAvail ? (lockOn ? t("Ligada: o Fidus pede sua digital ao abrir") : t("Desligada")) : t("Disponível no app atualizado, com digital ou rosto cadastrados")}</Text></View>
          <Text style={{ color: lockOn ? GREEN : c.sub, fontWeight: "700" }}>{lockOn ? t("Ligada") : t("Ligar")}</Text></Card>
        <Card c={c} style={{ flexDirection: "column", alignItems: "stretch", gap: 4 }}>
          <Text style={{ color: c.sub, fontSize: 12 }}>{t("ESTE APARELHO")}</Text>
          <Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{device?.device_name || t("Este celular")}</Text>
          <Text style={{ color: c.sub, fontSize: 12 }}>{t("Sua conta funciona em um aparelho por vez. Entrar em outro desconecta este.")}</Text>
          <Text style={{ color: c.sub, fontSize: 12, marginTop: 6 }}>
            {SpeechRec ? "✅" : "❌"} {t("Transcrição no celular")}{SpeechRec ? "" : ` (${t("precisa do APK novo")})`}{"\n"}
            {me?.natural_voice ? "✅" : "❌"} {t("Voz natural")}{me?.natural_voice ? "" : ` (${t("falta a chave no servidor")})`}{"\n"}
            {t("Versão")}: 0.9.8 · {UPDATE_ID.slice(0, 8)}</Text>
          <Pressable onPress={logoutAll} style={{ marginTop: 6 }}><Text style={{ color: RED, fontWeight: "600" }}>{t("Sair de todos os aparelhos")}</Text></Pressable>
        </Card>
        <Card c={c} onPress={reconnectGoogle}>
          <View style={{ flex: 1 }}><Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>Google</Text>
            <Text style={{ color: c.sub, fontSize: 14 }}>{me?.google_connected ? t("Conectado · tocar para reconectar") : t("Não conectado · tocar para conectar")}</Text></View>
          <Text style={{ color: c.sub }}>›</Text></Card>
        {!!pendingMeet && <Card c={c} onPress={() => { const p = pendingMeet; setPendingMeet(null); setScreen("chat"); sendMeetingFile(p); }}>
          <Text style={{ color: c.text, flex: 1, fontSize: 15 }}>🎙 {t("Reenviar reunião")}</Text></Card>}
        <Card c={c} onPress={exportData}>
          <View style={{ flex: 1 }}><Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{t("Exportar meus dados")}</Text>
            <Text style={{ color: c.sub, fontSize: 14 }}>{t("Um arquivo com tudo: conversas, gastos, recibos, documentos")}</Text></View>
          <Text style={{ color: c.sub }}>›</Text></Card>
        <Card c={c} style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}>
          <Pressable onPress={() => setDelOpen(!delOpen)}><Text style={{ color: RED, fontWeight: "600" }}>{t("Apagar minha conta")}</Text></Pressable>
          {delOpen && (<>
            <Text style={{ color: c.sub, fontSize: 14 }}>{t("Apaga a conta e todos os dados. Não dá para desfazer pelo app. Para confirmar, digite APAGAR.")}</Text>
            <View style={[s.row, { gap: 8 }]}>
              <TextInput style={[s.input, s.flex, { color: c.text, backgroundColor: c.bg, marginBottom: 0 }]} value={delWord} onChangeText={setDelWord}
                autoCapitalize="characters" placeholder="APAGAR" placeholderTextColor={c.sub} />
              <Pressable style={[s.primarySm, { backgroundColor: RED, justifyContent: "center" }]} onPress={deleteAccount}>
                <Text style={s.primaryText}>{t("Apagar")}</Text></Pressable>
            </View>
          </>)}
        </Card>
        <Card c={c} onPress={() => Linking.openURL(`mailto:${SUPPORT_EMAIL}?subject=Fidus`).catch(() => {})}>
          <View style={{ flex: 1 }}><Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{t("Ajuda e contato")}</Text>
            <Text style={{ color: c.sub, fontSize: 14 }}>{SUPPORT_EMAIL}</Text></View>
          <Text style={{ color: c.sub }}>›</Text></Card>
        <Card c={c} onPress={testConnection}><Text style={{ color: c.text, flex: 1, fontSize: 15 }}>{t("Testar conexão")}</Text></Card>
        <Card c={c} onPress={() => Alert.alert(t("Sair da conta?"), "", [{ text: t("Cancelar"), style: "cancel" }, { text: t("Sair"), style: "destructive", onPress: logout }])}>
          <Text style={{ color: RED, fontWeight: "600", flex: 1 }}>{t("Sair da conta")}</Text></Card>
        <Text style={{ color: c.sub, fontSize: 11, textAlign: "center" }}>{base()}</Text>
      </ScrollView>
    );
    return null;
  }


  const userInitial = (me?.name || me?.email || "?").trim().charAt(0).toUpperCase();

  return (
    <SafeAreaView edges={["top", "bottom"]} style={[s.flex, { backgroundColor: c.bg }]}>
      <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={s.topbar}>
          <Pressable onPress={openDrawer} hitSlop={10} style={s.iconBtn} accessibilityLabel={t("Menu")}>
            <MenuIcon color={c.text} /></Pressable>
          <Text style={[s.header, { color: c.text, flex: 1, fontSize: 15 }]} numberOfLines={1}>{SCREEN_TITLE()[screen]}</Text>
          {screen === "chat" ? (<>
            <Pressable style={[s.chip, meeting ? { backgroundColor: RED, borderColor: RED } : { borderColor: c.line }]} onPress={meetingMenu}
              accessibilityLabel={t("Gravar reunião")}>
              <Text style={{ color: meeting ? "#fff" : c.text, fontSize: 13, fontWeight: meeting ? "700" : "400" }}>
                {meeting ? `● ${fmtClock(meetSecs)}` : `🎙 ${t("Reunião")}`}</Text></Pressable>
            <Pressable onPress={newChat} hitSlop={10} style={s.iconBtn} accessibilityLabel={t("Nova conversa")}>
              <ComposeIcon color={c.text} /></Pressable>
          </>) : (
            <Pressable onPress={() => setScreen("chat")} hitSlop={10} style={[s.chip, { borderColor: c.line }]}>
              <Text style={{ color: c.text, fontSize: 13 }}>{t("Conversa")}</Text></Pressable>
          )}
        </View>
        {screen !== "chat" ? renderScreen() : (<>
        <View style={s.flex}>
        <FlatList
          ref={listRef} data={items} keyExtractor={(i) => i.id} contentContainerStyle={{ padding: 16, gap: 10 }}
          keyboardShouldPersistTaps="handled" scrollEventThrottle={100}
          onScroll={(e) => {
            const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
            setAtBottom(contentSize.height - (contentOffset.y + layoutMeasurement.height) < 250);
          }}
          ListFooterComponent={busy ? (
            <View style={[s.bubble, { backgroundColor: c.card, flexDirection: "row", alignItems: "center", gap: 8 }]}>
              <ActivityIndicator color={c.sub} /><Text style={{ color: c.sub }}>{t("Fidus está pensando…")}</Text>
            </View>) : null}
          ListEmptyComponent={<Text style={[s.empty, { color: c.sub }]}>
            {t("Toque no microfone, fale e toque de novo para enviar.\nEx.: “Marca visita técnica dia 12 às 4pm”,\n“Me lembra de pagar o IVA dia 5”,\n“Paguei 60 libras de gasolina, HomB” ou\n📷 mande a foto de um recibo ou documento.\n\n🎙 Reunião no topo grava e gera a ata.")}
          </Text>}
          renderItem={({ item }) => {
            if (item.type === "user")
              return <View style={[s.bubble, s.userBubble]}><LinkText text={item.text} style={s.userText} linkColor={MINT} /></View>;
            if (item.type === "fidus")
              return <View style={{ alignSelf: "flex-start", maxWidth: "85%" }}>
                <View style={[s.bubble, { backgroundColor: c.card, maxWidth: "100%" }]}>
                  <LinkText text={item.text} style={{ color: c.text, fontSize: 17, lineHeight: 26 }} linkColor={dark ? "#7DB3FF" : "#1E5BD8"} /></View>
                <View style={{ flexDirection: "row", gap: 2, marginTop: 2, marginLeft: 4 }}>
                  {[1, -1].map((v) => (
                    <Pressable key={v} hitSlop={6} onPress={() => sendFeedback(item.id, v)} accessibilityLabel={v > 0 ? t("Resposta boa") : t("Resposta ruim")}
                      style={{ paddingHorizontal: 6, paddingVertical: 2, opacity: fb[item.id] === undefined ? 0.45 : fb[item.id] === v ? 1 : 0.2 }}>
                      <Text style={{ fontSize: 13 }}>{v > 0 ? "👍" : "👎"}</Text></Pressable>))}
                </View>
              </View>;
            if (item.type === "nps")
              return (
                <View style={[s.draft, { backgroundColor: c.card, borderColor: MINT }]}>
                  <Text style={{ color: c.text, fontWeight: "700" }}>{t("De 0 a 10, quanto você indicaria o Fidus a um amigo?")}</Text>
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                    {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                      <Pressable key={n} onPress={() => setNpsScore(n)} accessibilityLabel={String(n)}
                        style={{ width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", borderWidth: 1,
                          borderColor: npsScore === n ? MINT : c.line, backgroundColor: npsScore === n ? MINT : "transparent" }}>
                        <Text style={{ color: npsScore === n ? NAVY : c.text, fontWeight: "700" }}>{n}</Text></Pressable>))}
                  </View>
                  {npsScore != null && (
                    <TextInput style={[s.input, { color: c.text, backgroundColor: c.bg, marginTop: 10, marginBottom: 0 }]} value={npsText} onChangeText={setNpsText}
                      placeholder={t("O que faria o Fidus ser ainda melhor? (opcional)")} placeholderTextColor={c.sub} multiline />)}
                  <View style={[s.row, { marginTop: 10 }]}>
                    <Pressable style={[s.secondary, { borderColor: c.sub }]} onPress={() => skipNps(item.id)}><Text style={{ color: c.text }}>{t("Agora não")}</Text></Pressable>
                    <Pressable style={[s.primarySm, { opacity: npsScore == null ? 0.4 : 1 }]} disabled={npsScore == null} onPress={() => sendNps(item.id)}>
                      <Text style={s.primaryText}>{t("Enviar")}</Text></Pressable>
                  </View>
                </View>);
            if (item.type === "upsell")
              return <UpsellCard u={item.up} onClose={() => setItems((prev) => prev.filter((x) => x.id !== item.id))} />;
            if (item.type === "doc") {
              const d = item.doc;
              return (
                <Pressable onPress={() => openDoc(d)} style={[s.actCard, { backgroundColor: c.card, borderWidth: 1, borderColor: MINT }]}>
                  <Text style={s.actIcon}>📄</Text>
                  <View style={{ flex: 1 }}>
                    <Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{d.title}</Text>
                    {!!d.expires_on && <Text style={{ color: c.sub, fontSize: 12 }}>{t("vence {0}", `${fmtDay(d.expires_on)}/${d.expires_on.slice(0, 4)}`)}</Text>}
                  </View>
                  <Text style={{ color: MINT, fontWeight: "700" }}>{t("Abrir")}</Text>
                </Pressable>
              );
            }
            const a = item.action;
            if (a.kind === "calendar_invite") {
              return (
                <View style={[s.draft, { backgroundColor: c.card, borderColor: MINT }]}>
                  <Text style={[s.draftLabel, { color: c.sub }]}>{t("Convite")} · {a.status === "pending" ? t("aguardando você") : a.status === "sending" ? t("enviando…") : a.status === "sent" ? t("enviado ✓") : t("cancelado")}</Text>
                  <Text style={{ color: c.text, fontWeight: "600", fontSize: 16 }}>{a.payload.title}</Text>
                  {!!a.payload.start && <Text style={{ color: c.sub }}>{fmtDate(a.payload.start)}</Text>}
                  <Text style={{ color: c.text, marginVertical: 6 }}>{t("Para")}: {(a.payload.emails || []).join(", ")}</Text>
                  {a.status === "pending" && (
                    <View style={s.row}>
                      <Pressable style={[s.secondary, { borderColor: c.sub }]} onPress={() => cancel(a)}>
                        <Text style={{ color: c.text }}>{t("Cancelar")}</Text></Pressable>
                      <Pressable style={s.primarySm} onPress={() => confirmInvite(a)}>
                        <Text style={s.primaryText}>{t("Enviar convite")}</Text></Pressable>
                    </View>
                  )}
                </View>
              );
            }
            return <EmailCard key={a.id} a={a} c={c} dark={dark} onSend={() => confirmSend(a)} onCancel={() => cancel(a)}
              onSave={(p) => saveDraft(a, p)} onCopy={copyText}
              onEditing={(on) => { if (on) editingIds.current.add(a.id); else editingIds.current.delete(a.id); }} />;
          }}
        />
        {!atBottom && items.length > 3 && (
          <Pressable onPress={() => { listRef.current?.scrollToEnd({ animated: true }); setAtBottom(true); }}
            accessibilityLabel={t("Ir para o fim da conversa")}
            style={[s.toBottom, { backgroundColor: c.card, borderColor: c.line }]}>
            <ArrowUpIcon color={c.text} size={18} down />
          </Pressable>
        )}
        </View>
        {meeting && (
          <Pressable onPress={finishMeeting} style={[s.meetBar, { backgroundColor: c.card, borderColor: RED }]}>
            <Text style={{ color: RED, fontWeight: "800" }}>● REC {fmtClock(meetSecs)}</Text>
            <Text style={{ color: c.text, flex: 1, fontSize: 15 }}>{t("Gravando a reunião. Mantenha o Fidus aberto.")}</Text>
            <Text style={{ color: c.text, fontWeight: "700" }}>{t("Encerrar")}</Text>
          </Pressable>
        )}
        {!meeting && !recording && typed.length === 0 && kb === 0 && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} keyboardShouldPersistTaps="handled"
            contentContainerStyle={{ paddingHorizontal: 12, paddingVertical: 6, gap: 8, alignItems: "center" }}
            style={{ flexGrow: 0, flexShrink: 0, height: 54 }}>
            {SUGGESTIONS().map(([label, q]) => (
              <Pressable key={label} disabled={busy} onPress={() => sendText(q)}
                style={[s.chip, { borderColor: c.sub, backgroundColor: c.card, paddingVertical: 9, paddingHorizontal: 14 }]}>
                <Text style={{ color: c.text, fontSize: 14, lineHeight: 18 }} numberOfLines={1}>{label}</Text></Pressable>
            ))}
          </ScrollView>
        )}
        <View style={[s.bottom, Platform.OS === "android" && kb > 0 ? { marginBottom: Math.max(kb - insets.bottom, 0) + 56 } : null]}>
          <View style={[s.composer, { backgroundColor: c.card, borderColor: recording ? RED : c.line }]}>
            {recording ? (<>
              <Pressable onPress={cancelRec} accessibilityLabel={t("Cancelar gravação")} hitSlop={8}
                style={[s.iconBtn, { backgroundColor: dark ? "#22345A" : "#EEF1F6" }]}>
                <CloseIcon color={c.text} />
              </Pressable>
              <View style={{ flex: 1, flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 6 }}>
                <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: RED }} />
                <Text style={{ color: c.text, fontVariant: ["tabular-nums"], fontWeight: "600" }}>{fmtClock(recSecs)}</Text>
                <RecordingBars color={c.sub} />
                <Text style={{ color: c.sub, fontSize: 14 }} numberOfLines={1}>{t("Gravando…")}</Text>
              </View>
              <Pressable onPress={stopRec} accessibilityLabel={t("Enviar áudio")} style={[s.sendBtn2, { backgroundColor: NAVY }]}>
                <ArrowUpIcon color="#fff" />
              </Pressable>
            </>) : (<>
              <Pressable onPress={photoMenu} disabled={busy} accessibilityLabel={t("Adicionar foto ou arquivo")} hitSlop={6}
                style={[s.iconBtn, { borderWidth: 1, borderColor: dark ? "#2C3F66" : "#D5DCE6" }]}>
                <PlusIcon color={c.text} />
              </Pressable>
              <TextInput style={[s.composerInput, { color: c.text }]}
                placeholder={t("Fale ou escreva…")} multiline placeholderTextColor={c.sub} value={typed}
                onChangeText={setTyped} />{/* Enter só pula linha: envia apenas pelo botão */}
              {activeReq ? (
                <Pressable onPress={stopRequest} accessibilityLabel={t("Parar")} hitSlop={6}
                  style={[s.sendBtn2, { backgroundColor: NAVY }]}>
                  <View style={{ width: 13, height: 13, borderRadius: 2, backgroundColor: "#fff" }} />
                </Pressable>
              ) : typed.trim().length > 0 ? (
                <Pressable onPress={() => sendText()} disabled={busy} accessibilityLabel={t("Enviar")}
                  style={[s.sendBtn2, { backgroundColor: busy ? c.sub : NAVY }]}>
                  <ArrowUpIcon color="#fff" />
                </Pressable>
              ) : (
                <>
                  <Pressable onPress={toggleRec} disabled={busy || meeting} accessibilityLabel={t("Gravar áudio")} hitSlop={6}
                    style={[s.iconBtn, { opacity: busy || meeting ? 0.4 : 1 }]}>
                    <MicIcon color={c.text} size={24} />
                  </Pressable>
                  <Pressable onPress={openVoice} disabled={busy || meeting} accessibilityLabel={t("Modo conversa")}
                    style={[s.sendBtn2, { backgroundColor: NAVY, opacity: busy || meeting ? 0.4 : 1 }]}>
                    <WaveIcon color="#fff" />
                  </Pressable>
                </>
              )}
            </>)}
          </View>
        </View>
        </>)}
      </KeyboardAvoidingView>

      {/* Menu lateral (como no Claude) */}
      <Modal visible={drawer} transparent animationType="none" onRequestClose={() => closeDrawer()} statusBarTranslucent>
        <View style={{ flex: 1, flexDirection: "row" }}>
          <Animated.View style={[s.drawer, { backgroundColor: c.bg, paddingTop: insets.top + 10, paddingBottom: insets.bottom + 10,
            transform: [{ translateX: drawerX }] }]}>
            <Text style={[s.logo, { color: c.text, fontSize: 26, paddingHorizontal: 18, marginBottom: 8 }]}>Fidus</Text>
            <Pressable onPress={newChat} style={[s.drawerNew, { backgroundColor: c.card, borderColor: c.line }]}>
              <ComposeIcon color={c.text} size={20} /><Text style={{ color: c.text, fontWeight: "700", fontSize: 15 }}>{t("Nova conversa")}</Text>
            </Pressable>
            <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 12 }}>
              {([
                ["convs", "💬", t("Conversas")], ["tasks", "📝", t("Tarefas")], ["docs", "📄", t("Documentos")],
                ["meetings", "🎙", t("Reuniões e atas")], ["expenses", "💷", t("Gastos e contas")],
                ["booking", "🔗", t("Link de agendamento")], ["activity", "✅", t("Atividade")],
                ["invite", "🎁", t("Convide e ganhe")],
                ...(me?.is_owner ? [["admin", "👥", t("Clientes")]] : []),
                ...(me?.staff_role ? [["panel", "📈", t("Painel da empresa")]] : []),
              ] as [Screen, string, string][]).map(([sc, ic, label]) => (
                <Pressable key={sc} onPress={() => go(sc)} style={[s.drawerItem, screen === sc && { backgroundColor: c.card }]}>
                  <Text style={{ fontSize: 17, width: 28 }}>{ic}</Text>
                  <Text style={{ color: c.text, fontSize: 15 }}>{label}</Text>
                </Pressable>
              ))}
              {convs.length > 0 && (<>
                <Text style={{ color: c.sub, fontSize: 12, marginTop: 14, marginBottom: 4, paddingHorizontal: 18 }}>{t("Recentes")}</Text>
                {convs.slice(0, 8).map((cv) => (
                  <Pressable key={cv.id} onPress={() => openConversation(cv.id)} style={s.drawerRecent}>
                    <Text style={{ color: c.text, fontSize: 14 }} numberOfLines={1}>{cv.title === "Conversa" ? t("Conversa") : cv.title}</Text>
                  </Pressable>
                ))}
              </>)}
            </ScrollView>
            <Pressable onPress={() => go("settings")} style={[s.drawerUser, { borderTopColor: c.line }]}>
              <View style={[s.avatar, { backgroundColor: NAVY }]}><Text style={{ color: "#fff", fontWeight: "800" }}>{userInitial}</Text></View>
              <View style={{ flex: 1 }}>
                <Text style={{ color: c.text, fontWeight: "700" }} numberOfLines={1}>{me?.name || me?.email || "Fidus"}</Text>
                <Text style={{ color: c.sub, fontSize: 12 }}>{t("Plano {0}", t(me?.plan_name || PLAN_NAMES[me?.plan] || ""))}</Text>
              </View>
              <Text style={{ color: c.sub, fontSize: 18 }}>⚙︎</Text>
            </Pressable>
          </Animated.View>
          <Pressable style={{ flex: 1, backgroundColor: "#0007" }} onPress={() => closeDrawer()} />
        </View>
      </Modal>

      <Modal visible={voiceOpen} animationType="fade" onRequestClose={closeVoice} statusBarTranslucent>
        <View style={{ flex: 1, backgroundColor: "#07090D", paddingTop: insets.top + 12, paddingBottom: insets.bottom + 20, paddingHorizontal: 24 }}>
          <View style={{ flexDirection: "row", alignItems: "center" }}>
            <Text style={{ color: "#F2F5F7", fontSize: 18, fontWeight: "700", flex: 1 }}>{t("Modo conversa")}</Text>
            <Pressable onPress={closeVoice} accessibilityLabel={t("Fechar modo conversa")} hitSlop={10}
              style={[s.iconBtn, { backgroundColor: "#161B23" }]}><CloseIcon color="#F2F5F7" /></Pressable>
          </View>
          <View style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: 28 }}>
            <Pressable onPress={tapVoiceCircle} accessibilityLabel={t("Enviar agora ou interromper")}>
              <Animated.View style={{ width: 190, height: 190, borderRadius: 95, alignItems: "center", justifyContent: "center",
                backgroundColor: vState === "thinking" ? "#1E2530" : vState === "speaking" ? "#2F5BD8" : MINT,
                transform: [{ scale: pulse }] }}>
                {vState === "thinking" ? <ActivityIndicator color="#F2F5F7" size="large" /> : <WaveIcon color="#07090D" size={56} />}
              </Animated.View>
            </Pressable>
            <Text style={{ color: "#F2F5F7", fontSize: 22, fontWeight: "700" }}>
              {vState === "listening" ? t("Ouvindo…") : vState === "thinking" ? t("Pensando…") : vState === "speaking" ? t("Falando…") : ""}</Text>
            {!!vHeard && <Text style={{ color: "#8D98A8", fontSize: 16, textAlign: "center" }} numberOfLines={3}>“{vHeard}”</Text>}
            {!!vReply && <Text style={{ color: "#F2F5F7", fontSize: 20, lineHeight: 28, textAlign: "center" }} numberOfLines={7}>{vReply}</Text>}
          </View>
          <Text style={{ color: "#6F7B8C", textAlign: "center", marginBottom: 14 }}>
            {t("Fale normalmente: quando você parar, eu respondo. Toque no círculo para enviar na hora ou para me interromper. Diga “tchau” para sair.")}</Text>
          <Pressable onPress={closeVoice} style={{ backgroundColor: "#161B23", borderRadius: 18, paddingVertical: 18, alignItems: "center" }}>
            <Text style={{ color: "#F2F5F7", fontSize: 18, fontWeight: "700" }}>{t("Encerrar")}</Text></Pressable>
        </View>
      </Modal>

      <Modal visible={!!reader} animationType="slide" onRequestClose={() => setReader(null)}>
        <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: insets.top + 8, paddingBottom: insets.bottom }}>
          <View style={s.topbar}>
            <Text style={[s.header, { color: c.text, flex: 1, fontSize: 15 }]} numberOfLines={1}>{reader?.title}</Text>
            <Pressable onPress={() => reader && copyText(reader.text)} hitSlop={10} style={s.iconBtn}><CopyIcon color={c.text} /></Pressable>
            <Pressable onPress={() => setReader(null)} hitSlop={10} style={s.iconBtn}><CloseIcon color={c.text} /></Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: 16 }}>
            <LinkText text={reader?.text || ""} style={{ color: c.text, fontSize: 17, lineHeight: 26 }} linkColor={dark ? "#7DB3FF" : "#1E5BD8"} />
          </ScrollView>
        </View>
      </Modal>

      <Modal visible={!!sheet} transparent animationType="slide" onRequestClose={() => setSheet(null)}>
        <Pressable style={s.sheetBg} onPress={() => setSheet(null)}>
          <View style={[s.sheet, { backgroundColor: c.card, paddingBottom: 16 + insets.bottom, maxHeight: Dimensions.get("window").height * 0.8 }]}>
            <Text style={{ color: c.sub, marginBottom: 8 }} numberOfLines={1}>{sheet?.title}</Text>
            <ScrollView>
              {(sheet?.items || []).map(([label, fn]) => (
                <Pressable key={label} style={[s.sheetBtn, { borderColor: c.sub + "55" }]} onPress={() => { setSheet(null); setTimeout(fn, 250); }}>
                  <Text style={{ color: c.text, fontSize: 17 }}>{label}</Text></Pressable>
              ))}
            </ScrollView>
            <Pressable style={[s.sheetBtn, { borderBottomWidth: 0 }]} onPress={() => setSheet(null)}>
              <Text style={{ color: c.sub, fontSize: 17 }}>{t("Cancelar")}</Text></Pressable>
          </View>
        </Pressable>
      </Modal>

      {!!toast && (
        <View pointerEvents="none" style={[s.toast, { bottom: insets.bottom + 90 }]}>
          <Text style={{ color: "#fff", fontWeight: "600" }}>{toast}</Text></View>
      )}
      <Modal visible={locked} animationType="fade" onRequestClose={() => {}} statusBarTranslucent>
        <View style={{ flex: 1, backgroundColor: c.bg, alignItems: "center", justifyContent: "center", gap: 18, padding: 24 }}>
          <Text style={[s.logo, { color: c.text }]}>Fidus</Text>
          <Text style={{ color: c.sub, textAlign: "center" }}>{t("Use sua digital ou rosto para abrir.")}</Text>
          <Pressable style={[s.primary, { paddingHorizontal: 32 }]} onPress={unlock}><Text style={s.primaryText}>{t("Desbloquear")}</Text></Pressable>
          <Pressable onPress={() => Alert.alert(t("Sair da conta?"), t("Você vai precisar entrar de novo com o Google ou o e-mail."), [
            { text: t("Cancelar"), style: "cancel" }, { text: t("Sair"), style: "destructive", onPress: logout }])} style={{ marginTop: 8 }}>
            <Text style={{ color: c.sub, textDecorationLine: "underline" }}>{t("Sair da conta")}</Text></Pressable>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

// Textos do app para tradução (gerado a partir das chamadas t("...") deste arquivo)
// @i18n-keys-start
const I18N_KEYS: string[] = [
  "Voz e texto sem limite",
  "Agenda, lembretes e bom dia",
  "E-mail com aprovação",
  "Gastos e recibos de 1 carteira",
  "Documentos com validade",
  "Tarefas",
  "Empresas e moedas ilimitadas",
  "Link de agendamento para clientes",
  "Ata de reunião automática",
  "Pacote do contador",
  "Alerta de assinaturas",
  "Resumo da semana",
  "Banco conectado: gastos entram sozinhos",
  "Cobrança e fatura para clientes",
  "Mais 1 pessoa na conta + acesso do contador",
  "Atas sem limite e suporte prioritário",
  "link de agendamento",
  "atas de reunião",
  "gravar reuniões e gerar a ata",
  "pacote do contador",
  "alerta de assinaturas",
  "resumo da semana",
  "gastos de mais de uma empresa",
  "banco conectado",
  "cobrança e fatura para clientes",
  "mais uma pessoa na conta",
  "Negócio",
  "Essencial",
  "Premium",
  "combustível",
  "alimentação",
  "transporte",
  "materiais",
  "ferramentas",
  "manutenção",
  "escritório",
  "software",
  "telefone e internet",
  "impostos e taxas",
  "moradia",
  "saúde",
  "lazer",
  "viagem",
  "salários e prestadores",
  "outros",
  "código expirado. Peça um novo.",
  "código errado.",
  "este e-mail não tem acesso ao Fidus.",
  "esta conta entra com o Google.",
  "muitas tentativas. Tente amanhã ou entre com o Google.",
  "☀️ Bom dia",
  "Bom dia! O que eu tenho hoje?",
  "💷 Gastos do mês",
  "Quanto eu gastei este mês, por empresa?",
  "📝 Tarefas",
  "Quais são minhas tarefas abertas?",
  "📊 Minha semana",
  "Como foi minha semana?",
  "🔗 Link de agendamento",
  "Me manda meu link de agendamento.",
  "🔁 Assinaturas",
  "Quais assinaturas e cobranças recorrentes eu pago?",
  "Agenda",
  "E-mail",
  "Gasto",
  "Lembrete",
  "Tarefa",
  "Documento",
  "Conta fixa",
  "Convite",
  "Reunião",
  "Agendamento",
  "Contador",
  "Planilha",
  "Desfeito",
  "Cancelado",
  "Aguardando você",
  "Enviado",
  "Removida",
  "Apagado",
  "Lançado",
  "Concluída",
  "Guardado",
  "Cadastrada",
  "Ata pronta",
  "Agendado",
  "Gerado",
  "Alterada",
  "Criado",
  "Link",
  "Não consegui abrir este link.",
  "Enviando…",
  "Enviado ✓",
  "Descartado",
  "Email",
  "Editar",
  "Copiar",
  "Para",
  "Assunto",
  "Enviar",
  "Cancelar",
  "Salvar",
  "Toque na seta azul ou diga “envia”.",
  "Descartar",
  "Assinatura confirmada",
  "Plano {0}",
  "A loja confirmou o pagamento. O plano novo aparece em alguns minutos.",
  "Assinatura",
  "Compras restauradas",
  "Erro",
  "A conexão caiu. Buscando a resposta no servidor…",
  "Não consegui buscar a resposta. Confira sua internet e veja a Atividade antes de repetir o pedido.",
  "Você saiu deste aparelho",
  "Sua conta do Fidus foi aberta em outro aparelho. Cada conta funciona em um aparelho por vez. Para usar aqui, entre de novo.",
  "Seu acesso foi encerrado. Entre de novo para continuar.",
  "o servidor demorou demais para responder",
  "Conexão",
  "Conexão ok.",
  "conectado",
  "não conectado",
  "Erro de conexão",
  "Atividade",
  "Bom dia ☀️",
  "Sua agenda, tarefas e contas de hoje estão prontas no Fidus.",
  "Sua semana com o Fidus 📊",
  "Veja o que foi resolvido e o que vem pela frente.",
  "permissão do microfone negada.",
  "ao iniciar a gravação da reunião",
  "Gravar reuniões e gerar a ata faz parte do plano Negócio.",
  "Gravar reunião",
  "Deixe o celular na mesa. No fim, o Fidus transcreve, resume e cria suas tarefas.",
  "Mantenha a tela ligada e o Fidus aberto durante a gravação.",
  "Avise os participantes que a reunião está sendo gravada.",
  "Começar",
  "Encerrar reunião?",
  "{0} gravados.",
  "Continuar gravando",
  "Gerar ata",
  "nenhum áudio foi gravado.",
  "Reunião gravada",
  "Recebi a gravação. Estou transcrevendo e preparando a ata; aviso aqui quando ficar pronta (leva alguns minutos).",
  "ao enviar a reunião",
  "A gravação ficou guardada: abra o menu > Configurações > Reenviar reunião.",
  "Ata pronta 🎙",
  "Sua reunião",
  "na ata",
  "...",
  "Um instante.",
  "Deixa eu ver.",
  "Já vejo isso.",
  "Feito.",
  "Pode falar. Eu escuto e respondo em voz alta.",
  "Pode falar. (Para ouvir as respostas em voz alta, instale o APK novo.)",
  "Pode falar.",
  "Toque no círculo quando quiser falar.",
  "Não consegui abrir o microfone",
  "Não entendi. Pode repetir?",
  "Até mais!",
  "Falha de conexão",
  "Perdi a conexão com o servidor. Tente de novo em instantes.",
  "Apagar tarefa?",
  "Não",
  "Apagar",
  "Apagar o gasto \"{0}\"?",
  "Apagar a tarefa \"{0}\"?",
  "Reabrir a tarefa \"{0}\"?",
  "Apagar o documento \"{0}\"?",
  "Remover a conta fixa \"{0}\" e o aviso mensal?",
  "Apagar o lembrete \"{0}\"?",
  "Apagar o pacote \"{0}\"?",
  "Desfazer?",
  "Apagar \"{0}\" da sua agenda?",
  "Desfazer",
  "Sair de todos os aparelhos?",
  "A conta será desconectada em todos os aparelhos, inclusive neste.",
  "Sair de todos",
  "Desbloquear o Fidus",
  "Responder áudios em voz alta",
  "Instale o APK novo para o Fidus falar.",
  "O Fidus vai responder seus áudios falando",
  "Respostas aos áudios só por escrito",
  "Trava",
  "Este celular não tem digital ou rosto cadastrados, ou o app precisa ser atualizado.",
  "Desligar a trava",
  "Ligar a trava",
  "Trava ligada",
  "Trava desligada",
  "Código",
  "Digite o código de 8 letras que apareceu depois do Google.",
  "código inválido ou expirado. Entre com o Google de novo.",
  "erro",
  "Não deu certo",
  "Digite um e-mail válido.",
  "Muitos códigos pedidos. Tente mais tarde.",
  "Digite os 6 números que chegaram no seu e-mail.",
  "Clientes",
  "Digite o e-mail Google da pessoa.",
  "Convite criado",
  "{0} já pode entrar com o Google no app (plano {1}).",
  "Convidar {0} no plano:",
  "Mudar para {0}",
  "Suspender acesso",
  "Reativar acesso",
  "permissão do microfone negada. Libere nas configurações do celular.",
  "ao iniciar gravação",
  "ao parar gravação",
  "nenhum áudio foi gravado. Tente de novo.",
  "permissão negada para câmera/galeria.",
  "Foto enviada",
  "foto",
  "Recibo, fatura, contrato ou documento",
  "Tirar foto",
  "Escolher da galeria",
  "PDF",
  "arquivo grande demais (máx. 15 MB).",
  "Arquivo",
  "arquivo",
  "Pedido cancelado. Se algo já tinha sido feito, está na Atividade, com Desfazer.",
  "Enviar convite?",
  "O Google manda o convite por e-mail.",
  "Falha ao enviar",
  "Rascunho salvo",
  "Rascunho",
  "Enviar e-mail?",
  "Copiado",
  "Carteira",
  "Moeda com 3 letras, ex. GBP, EUR, BRL",
  "Carteira salva",
  "Remover esta carteira? Os gastos já lançados nela continuam guardados.",
  "Remover",
  "Ainda processando…",
  "Idioma do Fidus",
  "Salvo",
  "Obrigado!",
  "Painel da empresa",
  "Preparando seus dados…",
  "Seus dados",
  "O arquivo com todos os seus dados está pronto. Ele também fica em Documentos.",
  "Fechar",
  "Baixar",
  "Conta apagada",
  "Sua conta foi apagada. Se você tinha assinatura pela Google Play ou App Store, cancele também por lá.",
  "Digite APAGAR para confirmar.",
  "Estou usando o Fidus, um assessor pessoal por voz: agenda, e-mails, gastos e recibos. Com o meu convite você ganha {0} dias grátis: {1} (código {2})",
  "Pronto! Você ganhou {0} dias grátis.",
  "Anual",
  "Mensal",
  "convite: dias grátis",
  "A assinatura pelo app chega em breve. Por enquanto, fale com a gente pelo e-mail de suporte.",
  "Conversas",
  "Documentos",
  "Reuniões e atas",
  "Gastos e contas",
  "Link de agendamento",
  "Convide e ganhe",
  "Configurações",
  "Fale. O Fidus resolve.",
  "Entrar com o Google",
  "Entrar com e-mail",
  "seu@email.com",
  "Mandar código",
  "Mandamos um código de 6 números para {0}. Ele vale 10 minutos.",
  "Entrar",
  "Usar outro e-mail ou mandar de novo",
  "Tem um código de convite? (opcional)",
  "Depois do Google, se o app não abrir sozinho, digite o código:",
  "Fechar opções avançadas",
  "Opções avançadas",
  "Token de administrador",
  "Entrar com token",
  "Carregando…",
  "{0} faz parte do plano {1}.",
  "PLANO {0}",
  "/mês · ou {0}/ano",
  "Libera {0} e mais:",
  "Agora não",
  "Conhecer o {0}",
  "E-mail Google para convidar",
  "Convidar",
  "{0} conta(s) · {1} convite(s) aguardando",
  "você",
  "{0} ações no mês",
  "Google ok",
  "sem Google",
  "IA",
  "{0} trocas de aparelho",
  "SUSPENSO",
  "Nova tarefa…",
  "Nenhuma tarefa aberta.\nDiga, por exemplo: “cria a tarefa de revisar o contrato até sexta”.",
  "Concluir",
  "atrasada · era {0}",
  "até {0}",
  "prioridade alta",
  "coisas que o Fidus resolveu por você este mês",
  "poupados (estimativa)",
  "Nada por aqui ainda.\nTudo o que o Fidus fizer por você aparece nesta lista.",
  "Nenhuma conversa ainda.",
  "Conversa",
  "{0} mensagens",
  "Buscar documento…",
  "Nenhum documento guardado.\nMande a foto de um seguro, contrato ou carta e o Fidus guarda aqui.",
  "vence {0}",
  "Abrir",
  "Gravar reunião agora",
  "Nenhuma reunião gravada ainda.",
  "ata pronta",
  "processando",
  "{0} lançamentos",
  "Todas",
  "Nova carteira",
  "NOVA CARTEIRA",
  "Nome, ex. Pessoal BR",
  "Moeda, ex. BRL",
  "POR CARTEIRA",
  "POR CATEGORIA",
  "ÚLTIMOS LANÇAMENTOS",
  "CONTAS FIXAS",
  "dia {0}",
  "Nenhum gasto neste mês.\nDiga “paguei 30 libras de gasolina” ou mande a foto do recibo.",
  "Exportar {0} para o contador",
  "Exportar o mês para o contador",
  "Toque e segure uma carteira para remover.",
  "Mande este link para clientes marcarem horário direto na sua agenda, só nos horários livres.",
  "Compartilhar",
  "Dias",
  "Horário",
  "Antecedência",
  "Para mudar dias, horários ou tipos de atendimento, peça ao Fidus na conversa.",
  "CONVIDE E GANHE",
  "{0}% de desconto na sua próxima cobrança",
  "Para cada amigo que assinar o Fidus. Seu amigo ganha {0} dias grátis.",
  "Enviar convite",
  "Copiar link",
  "Amigos convidados",
  "Já assinaram",
  "Descontos guardados",
  "Próxima cobrança",
  "sem desconto",
  "Como funciona: o desconto entra quando o amigo paga o primeiro mês. Os descontos não somam: vale um por cobrança, e os que sobram ficam para as cobranças seguintes.",
  "Alguém te convidou?",
  "Usar",
  "Você entrou pelo convite de {0} 🎁",
  "O painel mostra a saúde do sistema, o uso do Fidus (HEART), o negócio e a equipe. Abra no computador e digite o código.",
  "Gerar código de acesso",
  "Vale 5 minutos e só uma vez.",
  "Copiar endereço",
  "Abrir aqui",
  "SEU NOME",
  "Idioma",
  "SEU PLANO",
  "/mês",
  "ou {0}/ano (2 meses grátis)",
  "Atual",
  "Escolher",
  "Gerenciar assinatura",
  "Trocar forma de pagamento ou cancelar, direto na loja",
  "Restaurar compras",
  "Voz masculina",
  "Voz feminina",
  "Voz do Fidus",
  "Toque para trocar",
  "Masculina",
  "Feminina",
  "Disponível no app atualizado",
  "Ligado: quando você manda áudio, o Fidus responde falando",
  "Desligado: respostas só por escrito",
  "Ligado",
  "Ligar",
  "Trava com digital ou rosto",
  "Ligada: o Fidus pede sua digital ao abrir",
  "Desligada",
  "Disponível no app atualizado, com digital ou rosto cadastrados",
  "Ligada",
  "ESTE APARELHO",
  "Este celular",
  "Sua conta funciona em um aparelho por vez. Entrar em outro desconecta este.",
  "Transcrição no celular",
  "precisa do APK novo",
  "Voz natural",
  "falta a chave no servidor",
  "Versão",
  "Sair de todos os aparelhos",
  "Conectado · tocar para reconectar",
  "Não conectado · tocar para conectar",
  "Reenviar reunião",
  "Exportar meus dados",
  "Um arquivo com tudo: conversas, gastos, recibos, documentos",
  "Apagar minha conta",
  "Apaga a conta e todos os dados. Não dá para desfazer pelo app. Para confirmar, digite APAGAR.",
  "Ajuda e contato",
  "Testar conexão",
  "Sair da conta?",
  "Sair",
  "Sair da conta",
  "Menu",
  "Nova conversa",
  "Fidus está pensando…",
  "Toque no microfone, fale e toque de novo para enviar.\nEx.: “Marca visita técnica dia 12 às 4pm”,\n“Me lembra de pagar o IVA dia 5”,\n“Paguei 60 libras de gasolina, HomB” ou\n📷 mande a foto de um recibo ou documento.\n\n🎙 Reunião no topo grava e gera a ata.",
  "Resposta boa",
  "Resposta ruim",
  "De 0 a 10, quanto você indicaria o Fidus a um amigo?",
  "O que faria o Fidus ser ainda melhor? (opcional)",
  "aguardando você",
  "enviando…",
  "enviado ✓",
  "cancelado",
  "Ir para o fim da conversa",
  "Gravando a reunião. Mantenha o Fidus aberto.",
  "Encerrar",
  "Cancelar gravação",
  "Gravando…",
  "Enviar áudio",
  "Adicionar foto ou arquivo",
  "Fale ou escreva…",
  "Parar",
  "Gravar áudio",
  "Modo conversa",
  "Recentes",
  "Fechar modo conversa",
  "Enviar agora ou interromper",
  "Ouvindo…",
  "Pensando…",
  "Falando…",
  "Fale normalmente: quando você parar, eu respondo. Toque no círculo para enviar na hora ou para me interromper. Diga “tchau” para sair.",
  "Use sua digital ou rosto para abrir.",
  "Desbloquear",
  "Você vai precisar entrar de novo com o Google ou o e-mail.",
];
// @i18n-keys-end

const s = StyleSheet.create({
  composer: { flex: 1, flexDirection: "row", alignItems: "flex-end", gap: 6, borderWidth: 1, borderRadius: 26,
    paddingHorizontal: 8, paddingVertical: 7, minHeight: 54 },
  composerInput: { flex: 1, fontSize: 17, paddingHorizontal: 6, paddingTop: 9, paddingBottom: 9, maxHeight: 130 },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  sendBtn2: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  meetBar: { flexDirection: "row", alignItems: "center", gap: 10, marginHorizontal: 12, marginBottom: 8, padding: 12, borderRadius: 12, borderWidth: 1.5 },
  sheetBg: { flex: 1, backgroundColor: "#0008", justifyContent: "flex-end" },
  sheet: { borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: 16 },
  sheetBtn: { paddingVertical: 16, borderBottomWidth: StyleSheet.hairlineWidth },
  flex: { flex: 1 },
  setup: { flexGrow: 1, justifyContent: "center", padding: 24 },
  logo: { fontSize: 40, fontWeight: "700", marginBottom: 4 },
  actCard: { flexDirection: "row", alignItems: "center", gap: 12, borderRadius: 14, padding: 14 },
  actIcon: { fontSize: 22 },
  check: { width: 24, height: 24, borderRadius: 12, borderWidth: 2 },
  statCard: { flexDirection: "row", alignItems: "center", gap: 14, borderRadius: 14, padding: 16, marginBottom: 6 },
  pill: { alignSelf: "flex-start", borderWidth: 1, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2, marginBottom: 4 },
  topbar: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingTop: 6, paddingBottom: 4 },
  chip: { borderWidth: 1, borderRadius: 999, paddingVertical: 6, paddingHorizontal: 10 },
  header: { fontSize: 20, fontWeight: "700" },
  empty: { textAlign: "center", marginTop: 80, lineHeight: 22 },
  input: { borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, marginBottom: 12, fontSize: 16 },
  primary: { backgroundColor: NAVY, borderRadius: 12, padding: 14, alignItems: "center" },
  primarySm: { backgroundColor: NAVY, borderRadius: 10, paddingVertical: 10, paddingHorizontal: 20 },
  primaryText: { color: "#fff", fontWeight: "600" },
  secondary: { borderWidth: 1, borderRadius: 10, paddingVertical: 10, paddingHorizontal: 16 },
  bubble: { borderRadius: 16, paddingVertical: 12, paddingHorizontal: 14, maxWidth: "88%" },
  userBubble: { backgroundColor: NAVY, alignSelf: "flex-end" },
  userText: { color: "#fff", fontSize: 17, lineHeight: 26 },
  draft: { borderRadius: 14, padding: 14, borderWidth: 1.5 },
  draftLabel: { fontSize: 12, marginBottom: 6 },
  row: { flexDirection: "row", justifyContent: "flex-end", gap: 10 },
  bottom: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12 },
  // cartão de e-mail
  emailCard: { borderRadius: 16, borderWidth: 1, overflow: "hidden" },
  emailHead: { flexDirection: "row", alignItems: "center", paddingHorizontal: 14, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, gap: 4 },
  headBtn: { width: 34, height: 34, alignItems: "center", justifyContent: "center" },
  sendBlue: { width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center", marginLeft: 4 },
  emailRow: { flexDirection: "row", paddingHorizontal: 14, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth },
  emailFoot: { flexDirection: "row", alignItems: "center", paddingHorizontal: 14, paddingVertical: 10, borderTopWidth: StyleSheet.hairlineWidth, gap: 10 },
  editInput: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 16 },
  // setinha para o fim da conversa
  toBottom: { position: "absolute", alignSelf: "center", bottom: 10, width: 40, height: 40, borderRadius: 20, borderWidth: 1,
    alignItems: "center", justifyContent: "center", elevation: 4, shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 6, shadowOffset: { width: 0, height: 2 } },
  // menu lateral
  drawer: { width: 300, maxWidth: "84%", height: "100%", elevation: 12 },
  drawerNew: { flexDirection: "row", alignItems: "center", gap: 10, marginHorizontal: 12, marginBottom: 10, paddingHorizontal: 14,
    paddingVertical: 12, borderRadius: 14, borderWidth: 1 },
  drawerItem: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 18, paddingVertical: 12, marginHorizontal: 6, borderRadius: 12 },
  drawerRecent: { paddingHorizontal: 18, paddingVertical: 9 },
  drawerUser: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingTop: 12, borderTopWidth: StyleSheet.hairlineWidth },
  avatar: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  kv: { flexDirection: "row", justifyContent: "space-between", gap: 10, paddingVertical: 4 },
  planRow: { flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderRadius: 12, padding: 12 },
  toast: { position: "absolute", alignSelf: "center", backgroundColor: "#000C", paddingHorizontal: 16, paddingVertical: 10, borderRadius: 999 },
});
