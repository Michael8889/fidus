import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, FlatList, Keyboard, KeyboardAvoidingView, Linking, Modal, Platform, Pressable,
  ScrollView, StyleSheet, Text, TextInput, View, useColorScheme,
} from "react-native";
import { AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder } from "expo-audio";
import { File } from "expo-file-system";
import * as Haptics from "expo-haptics";
import * as ImagePicker from "expo-image-picker";
import { SafeAreaProvider, SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import * as SecureStore from "expo-secure-store";

// Módulos nativos novos: só existem a partir do APK v0.5. Num APK antigo, a função some sem travar o app.
const opt = (load: () => any) => { try { return load(); } catch { return null; } };
const Notifications: any = opt(() => require("expo-notifications"));
const KeepAwake: any = opt(() => require("expo-keep-awake"));
const DocumentPicker: any = opt(() => require("expo-document-picker"));

// gravação de reunião: mono, 16 kHz, 32 kbps (1 h ≈ 15 MB) — suficiente para transcrever
const MEETING_PRESET: any = {
  ...RecordingPresets.HIGH_QUALITY, sampleRate: 16000, numberOfChannels: 1, bitRate: 32000,
  android: { ...(RecordingPresets.HIGH_QUALITY as any).android, sampleRate: 16000 },
  ios: { ...(RecordingPresets.HIGH_QUALITY as any).ios, sampleRate: 16000 },
};

const SUGGESTIONS: [string, string][] = [
  ["☀️ Bom dia", "Bom dia! O que eu tenho hoje?"],
  ["💷 Gastos do mês", "Quanto eu gastei este mês, por empresa?"],
  ["📝 Tarefas", "Quais são minhas tarefas abertas?"],
  ["📊 Minha semana", "Como foi minha semana?"],
  ["🔗 Link de agendamento", "Me manda meu link de agendamento."],
  ["🔁 Assinaturas", "Quais assinaturas e cobranças recorrentes eu pago?"],
];
const fmtClock = (sec: number) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;

type Draft = { to: string; subject: string; body: string; title?: string; start?: string; emails?: string[] };
type Action = { id: string; kind: string; status: string; payload: Draft };
type Doc = { document_id: number; title: string; expires_on?: string | null; url: string };
type Task = { id: number; title: string; due?: string | null; priority: string; status: string; overdue?: boolean };
type Item =
  | { id: string; type: "user"; text: string }
  | { id: string; type: "fidus"; text: string }
  | { id: string; type: "action"; action: Action }
  | { id: string; type: "doc"; doc: Doc }
  | { id: string; type: "upsell"; up: Upsell };
type Upsell = { feature_label: string; plan: string; name: string; month: number; year: number; highlights: string[]; current_plan: string; url: string };
const eur = (n: number) => `€${n.toFixed(2).replace(".", ",")}`;

const NAVY = "#0E1E3A";
const MINT = "#3DDC97";
const ICON: Record<string, string> = {
  event_created: "📅", event_deleted: "🗑", email_draft: "✉️", expense_added: "💷", expense_deleted: "🗑",
  reminder_created: "⏰", task_added: "📝", task_done: "✅", document_saved: "📄", bill_added: "🔁",
  bill_deleted: "🗑", meet_added: "🎥", invite_draft: "👥", meeting_summarized: "🎙", booking_received: "🗓",
  export_created: "📦",
};
const LABEL: Record<string, string> = {
  event_created: "Agenda", event_deleted: "Agenda", email_draft: "E-mail", expense_added: "Gasto", expense_deleted: "Gasto",
  reminder_created: "Lembrete", task_added: "Tarefa", task_done: "Tarefa", document_saved: "Documento",
  bill_added: "Conta fixa", bill_deleted: "Conta fixa", meet_added: "Agenda", invite_draft: "Convite",
  meeting_summarized: "Reunião", booking_received: "Agendamento", export_created: "Contador",
};
const fmtDay = (d?: string | null) => d ? `${d.slice(8, 10)}/${d.slice(5, 7)}` : "";
// selo de status: verbo claro + cor
const GREEN = "#2E9E6B", RED = "#D64545", AMBER = "#C98A00", GRAY = "#8A94A6";
function pill(kind: string, status: string): { text: string; color: string } {
  if (status === "desfeito") return { text: "Desfeito", color: GRAY };
  if (status === "cancelado") return { text: "Cancelado", color: GRAY };
  if (status === "aguardando você") return { text: "Aguardando você", color: AMBER };
  if (status === "enviado") return { text: "Enviado", color: GREEN };
  if (kind === "bill_deleted") return { text: "Removida", color: RED };
  if (kind.endsWith("_deleted")) return { text: "Apagado", color: RED };
  if (kind === "expense_added") return { text: "Lançado", color: GREEN };
  if (kind === "task_done") return { text: "Concluída", color: GREEN };
  if (kind === "document_saved") return { text: "Guardado", color: GREEN };
  if (kind === "bill_added") return { text: "Cadastrada", color: GREEN };
  if (kind === "meeting_summarized") return { text: "Ata pronta", color: GREEN };
  if (kind === "booking_received") return { text: "Agendado", color: GREEN };
  if (kind === "export_created") return { text: "Gerado", color: GREEN };
  return { text: "Criado", color: GREEN };
}
const fmtDate = (iso: string) => {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

export default function App() {
  return <SafeAreaProvider><FidusApp /></SafeAreaProvider>;
}

function FidusApp() {
  const dark = useColorScheme() === "dark";
  const c = dark ? { bg: "#0B1426", card: "#14223F", text: "#EEF2F8", sub: "#9AA8C0" }
                 : { bg: "#F5F7FB", card: "#FFFFFF", text: NAVY, sub: "#5B6B85" };

  const [server, setServer] = useState("");
  const [token, setToken] = useState("");
  const [configured, setConfigured] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const meetRec = useAudioRecorder(MEETING_PRESET);
  const [meeting, setMeeting] = useState(false);
  const [meetSecs, setMeetSecs] = useState(0);
  const [plan, setPlan] = useState<any>(null);
  const [sheet, setSheet] = useState<{ title: string; items: [string, () => void][] } | null>(null);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [typed, setTyped] = useState("");
  const listRef = useRef<FlatList>(null);
  const insets = useSafeAreaInsets();
  const [kb, setKb] = useState(0);
  const [tab, setTab] = useState<"chat" | "tasks" | "activity">("chat");
  const [acts, setActs] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [newTask, setNewTask] = useState("");
  const [actsLoading, setActsLoading] = useState(false);

  // Android (tela cheia): o teclado cobre o app, então empurramos o conteúdo para cima
  useEffect(() => {
    if (Platform.OS !== "android") return;
    const show = Keyboard.addListener("keyboardDidShow", (e) => {
      console.log("[Fidus] teclado", JSON.stringify(e.endCoordinates), "insets", JSON.stringify(insets));
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

  // ao abrir, carrega a conversa salva no servidor; na primeira abertura do dia, mostra o "bom dia"
  useEffect(() => {
    if (!configured) return;
    (async () => {
      await loadHistory();
      const n = new Date();
      const today = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
      try {
        if ((await SecureStore.getItemAsync("lastBrief")) === today) return;
        const b = await api("/v1/briefing", {}, 30000);
        if (b?.text) { push({ id: uid(), type: "fidus", text: b.text }); await SecureStore.setItemAsync("lastBrief", today); }
      } catch { /* sem bom dia hoje */ }
      try {  // segunda-feira: resumo da semana
        if (new Date().getDay() === 1 && (await SecureStore.getItemAsync("lastWeekly")) !== today) {
          const w = await api("/v1/weekly", {}, 30000);
          if (w?.text) { push({ id: uid(), type: "fidus", text: w.text }); await SecureStore.setItemAsync("lastWeekly", today); }
        }
      } catch { /* sem resumo semanal */ }
      setupNotifications();
      try { setPlan(await api("/v1/plan", {}, 15000)); } catch { /* servidor antigo */ }
    })();
  }, [configured]);

  // a conexão caiu no meio (troca de rede, 4G fraco, app em segundo plano). O servidor
  // normalmente termina o pedido mesmo assim, então buscamos a resposta no histórico.
  const isNetErr = (e: any) => !/^\d{3}:/.test(e?.message ?? "") && e?.name !== "AbortError";
  async function recover(e: any, before: number) {
    if (!isNetErr(e)) return push({ id: uid(), type: "fidus", text: `Erro: ${e?.message ?? e}` });
    push({ id: uid(), type: "fidus", text: "A conexão caiu. Buscando a resposta no servidor…" });
    for (let i = 0; i < 12; i++) {
      await new Promise((r) => setTimeout(r, 5000));
      const msgs = await loadHistory();
      if (msgs && msgs.length > before && msgs[msgs.length - 1].role === "assistant") return;
    }
    push({ id: uid(), type: "fidus", text: "Não consegui buscar a resposta. Confira sua internet e veja a aba Atividade antes de repetir o pedido." });
  }
  const histLen = useRef(0);  // quantas mensagens o servidor tinha na última vez que olhamos
  const historyCount = () => histLen.current;

  useEffect(() => {
    (async () => {
      const s = await SecureStore.getItemAsync("server");
      const t = await SecureStore.getItemAsync("token");
      if (s && t) { setServer(s); setToken(t); setConfigured(true); }
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
    console.log("[Fidus] ->", init.method || "GET", url);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const r = await fetch(url, {
        ...init, signal: ctrl.signal,
        headers: { Authorization: `Bearer ${token.trim()}`, ...(init.headers || {}) },
      });
      console.log("[Fidus] <-", r.status, path);
      if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
      return r.json();
    } catch (e: any) {
      console.log("[Fidus] erro", path, e?.message ?? e);
      if (e?.name === "AbortError") throw new Error("o servidor demorou demais para responder");
      throw e;
    } finally { clearTimeout(timer); }
  }

  async function testConnection() {
    push({ id: uid(), type: "fidus", text: `Testando ${base()} …` });
    try {
      const h = await api("/health", {}, 15000);
      push({ id: uid(), type: "fidus", text: `Conexão ok. Google: ${h.google_connected ? "conectado" : "não conectado"}.` });
    } catch (e: any) { push({ id: uid(), type: "fidus", text: `Erro de conexão: ${e?.message ?? e}` }); }
  }

  async function loadActivity() {
    setActsLoading(true);
    try { const r = await api("/v1/activity", {}, 15000); setActs(r.items || []); setStats(r.stats || null); }
    catch (e: any) { Alert.alert("Atividade", e?.message ?? String(e)); }
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
      if ((await SecureStore.getItemAsync("notifV")) === "1") return;  // já agendado
      await Notifications.cancelAllScheduledNotificationsAsync();
      const T = Notifications.SchedulableTriggerInputTypes;
      await Notifications.scheduleNotificationAsync({
        content: { title: "Bom dia ☀️", body: "Sua agenda, tarefas e contas de hoje estão prontas no Fidus." },
        trigger: { type: T.DAILY, hour: 8, minute: 0, channelId: "fidus" },
      });
      await Notifications.scheduleNotificationAsync({
        content: { title: "Sua semana com o Fidus 📊", body: "Veja o que foi resolvido e o que vem pela frente." },
        trigger: { type: T.WEEKLY, weekday: 2, hour: 8, minute: 5, channelId: "fidus" },
      });
      await SecureStore.setItemAsync("notifV", "1");
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
      if (!perm.granted) return fail("permissão do microfone negada.");
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true, allowsBackgroundRecording: true,
                                shouldPlayInBackground: true } as any);
      await meetRec.prepareToRecordAsync();
      meetRec.record();
      try { await KeepAwake?.activateKeepAwakeAsync("meeting"); } catch {}
      setMeetSecs(0); setMeeting(true); setTab("chat");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch (e: any) { fail(`ao iniciar a gravação da reunião: ${e?.message ?? e}`); }
  }

  function upsellLocal(feature: string) {
    const p = (plan?.plans || []).find((x: any) => x.id === "negocio");
    if (!p) return false;
    push({ id: uid(), type: "fidus", text: "Gravar reuniões e gerar a ata faz parte do plano Negócio." });
    push({ id: uid(), type: "upsell", up: { feature_label: feature, plan: p.id, name: p.name, month: p.month, year: p.year,
      highlights: p.highlights, current_plan: plan.name, url: plan.url } });
    return true;
  }

  function meetingMenu() {
    if (meeting) return finishMeeting();
    if (plan?.locked_features?.includes("meetings_record") && upsellLocal("gravar reuniões e gerar a ata")) return;
    Alert.alert("Gravar reunião", "Deixe o celular na mesa. No fim, o Fidus transcreve, resume e cria suas tarefas.\n\n"
      + (KeepAwake ? "" : "Mantenha a tela ligada e o Fidus aberto durante a gravação.\n\n")
      + "Avise os participantes que a reunião está sendo gravada.", [
      { text: "Cancelar", style: "cancel" },
      { text: "Começar", onPress: startMeeting },
    ]);
  }

  async function stopMeetingRecorder() {
    try { await meetRec.stop(); } catch {}
    try { KeepAwake?.deactivateKeepAwake("meeting"); } catch {}
    setMeeting(false);
  }

  function finishMeeting() {
    Alert.alert("Encerrar reunião?", `${fmtClock(meetSecs)} gravados.`, [
      { text: "Continuar gravando", style: "cancel" },
      { text: "Descartar", style: "destructive", onPress: () => stopMeetingRecorder() },
      { text: "Gerar ata", onPress: uploadMeeting },
    ]);
  }

  async function uploadMeeting() {
    const secs = meetSecs;
    await stopMeetingRecorder();
    const uri = meetRec.uri;
    if (!uri) return fail("nenhum áudio foi gravado.");
    push({ id: uid(), type: "user", text: `🎙 Reunião gravada (${fmtClock(secs)})` });
    await sendMeetingFile(uri);
  }

  async function sendMeetingFile(uri: string) {
    await SecureStore.setItemAsync("pendingMeeting", uri);  // se o envio falhar, dá para reenviar pelo menu ⋯
    setBusy(true);
    try {
      const audio_b64 = await new File(uri).base64();
      const ext = (uri.match(/\.[a-z0-9]+$/i)?.[0] || ".m4a").toLowerCase();
      const r = await api("/v1/meeting_b64", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audio_b64, ext }) }, 600000);
      if (r.locked) { await SecureStore.deleteItemAsync("pendingMeeting"); return showResult({ upsell: r.upsell }, false); }
      await SecureStore.deleteItemAsync("pendingMeeting");
      push({ id: uid(), type: "fidus", text: "Recebi a gravação. Estou transcrevendo e preparando a ata; aviso aqui quando ficar pronta (leva alguns minutos)." });
      pollMeeting(r.meeting_id);
    } catch (e: any) { fail(`ao enviar a reunião: ${e?.message ?? e}. A gravação ficou guardada: toque em ⋯ > Reenviar reunião.`); }
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
          try { await Notifications?.scheduleNotificationAsync({ content: { title: "Ata pronta 🎙", body: st.title || "Sua reunião" }, trigger: null }); } catch {}
          return;
        }
        if (st.status === "erro") return fail(`na ata: ${st.error}`);
      } catch { /* rede instável: tenta de novo */ }
    }
  }

  async function loadTasks() {
    setTasksLoading(true);
    try { setTasks((await api("/v1/tasks", {}, 15000)).tasks || []); }
    catch (e: any) { Alert.alert("Tarefas", e?.message ?? String(e)); }
    finally { setTasksLoading(false); }
  }

  async function toggleTask(t: Task) {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setTasks((prev) => prev.filter((x) => x.id !== t.id));  // some da lista na hora
    try { await api(`/v1/tasks/${t.id}/done`, { method: "POST" }); }
    catch (e: any) { Alert.alert("Tarefas", e?.message ?? String(e)); loadTasks(); }
  }

  async function addTaskQuick() {
    const title = newTask.trim();
    if (!title) return;
    setNewTask("");
    try {
      await api("/v1/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
      loadTasks();
    } catch (e: any) { Alert.alert("Tarefas", e?.message ?? String(e)); }
  }

  function removeTask(t: Task) {
    Alert.alert("Apagar tarefa?", t.title, [
      { text: "Não", style: "cancel" },
      { text: "Apagar", style: "destructive", onPress: async () => {
          try { await api(`/v1/tasks/${t.id}`, { method: "DELETE" }); loadTasks(); }
          catch (e: any) { Alert.alert("Erro", e?.message ?? String(e)); }
        } },
    ]);
  }

  function undo(a: any) {
    const what: Record<string, string> = {
      expense_added: `Apagar o gasto "${a.title}"?`, task_added: `Apagar a tarefa "${a.title}"?`,
      task_done: `Reabrir a tarefa "${a.title}"?`, document_saved: `Apagar o documento "${a.title}"?`,
      bill_added: `Remover a conta fixa "${a.title}" e o aviso mensal?`, reminder_created: `Apagar o lembrete "${a.title}"?`,
      export_created: `Apagar o pacote "${a.title}"?`,
    };
    Alert.alert("Desfazer?", what[a.kind] ?? `Apagar "${a.title}" da sua agenda?`, [
      { text: "Não", style: "cancel" },
      { text: "Desfazer", style: "destructive", onPress: async () => {
          try { await api(`/v1/activity/${a.id}/undo`, { method: "POST" }); loadActivity(); }
          catch (e: any) { Alert.alert("Erro", e?.message ?? String(e)); }
        } },
    ]);
  }

  async function logout() {
    await SecureStore.deleteItemAsync("server"); await SecureStore.deleteItemAsync("token");
    setConfigured(false);
  }

  function showResult(res: any, showTranscript = true) {
    histLen.current += 2;  // pedido + resposta
    if (showTranscript && res.transcript) push({ id: uid(), type: "user", text: res.transcript });
    if (res.reply) push({ id: uid(), type: "fidus", text: res.reply });
    for (const a of res.pending_actions || []) push({ id: uid(), type: "action", action: a });
    for (const d of res.documents || []) push({ id: uid(), type: "doc", doc: d });
    if (res.upsell) push({ id: uid(), type: "upsell", up: res.upsell });
  }

  // ---------- Voz: tocar para gravar, tocar de novo para enviar ----------
  const fail = (msg: string) => push({ id: uid(), type: "fidus", text: `Erro: ${msg}` });

  async function toggleRec() {
    if (busy) return;
    if (recording) return stopRec();
    try {
      const perm = await AudioModule.requestRecordingPermissionsAsync();
      if (!perm.granted) return fail("permissão do microfone negada. Libere em Configurações > Apps > Expo Go.");
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
      setRecording(true);
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    } catch (e: any) { fail(`ao iniciar gravação: ${e?.message ?? e}`); }
  }

  async function stopRec() {
    setRecording(false);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try { await recorder.stop(); } catch (e: any) { return fail(`ao parar gravação: ${e?.message ?? e}`); }
    const uri = recorder.uri;
    if (!uri) return fail("nenhum áudio foi gravado. Tente de novo.");
    setBusy(true);
    const before = historyCount();
    try {
      const audio_b64 = await new File(uri).base64();
      const ext = (uri.match(/\.[a-z0-9]+$/i)?.[0] || ".m4a").toLowerCase();
      showResult(await api("/v1/voice_b64", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audio_b64, ext }),
      }));
    } catch (e: any) { await recover(e, before); }
    finally { setBusy(false); }
  }

  // ---------- Foto: recibo ou documento ----------
  async function pickPhoto(source: "camera" | "library") {
    try {
      const perm = source === "camera"
        ? await ImagePicker.requestCameraPermissionsAsync()
        : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) return fail("permissão negada para câmera/galeria.");
      const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 0.5, base64: true };
      const res = source === "camera" ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
      if (res.canceled || !res.assets?.[0]?.base64) return;
      const asset = res.assets[0];
      const note = typed.trim();
      setTyped("");
      push({ id: uid(), type: "user", text: `📷 Foto enviada${note ? `: ${note}` : ""}` });
      setBusy(true);
      const before = historyCount();
      try {
        const media_type = asset.mimeType && ["image/jpeg", "image/png", "image/webp"].includes(asset.mimeType) ? asset.mimeType : "image/jpeg";
        showResult(await api("/v1/photo", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ image_b64: asset.base64, media_type, text: note }),
        }), false);
      } catch (e: any) { await recover(e, before); }
      finally { setBusy(false); }
    } catch (e: any) { fail(`foto: ${e?.message ?? e}`); }
  }

  function photoMenu() {
    setSheet({ title: "Recibo, fatura, contrato ou documento", items: [
      ["📷  Tirar foto", () => pickPhoto("camera")],
      ["🖼  Escolher da galeria", () => pickPhoto("library")],
      ...(DocumentPicker ? [["📎  PDF", pickPdf] as [string, () => void]] : []),
    ] });
  }

  async function pickPdf() {
    try {
      // só PDF: fotos vão pela câmera/galeria, que já reduzem o tamanho
      const res = await DocumentPicker.getDocumentAsync({ type: "application/pdf", copyToCacheDirectory: true });
      if (res.canceled || !res.assets?.[0]) return;
      const a = res.assets[0];
      const media_type = "application/pdf";
      if ((a.size || 0) > 15 * 1024 * 1024) return fail("arquivo grande demais (máx. 15 MB).");
      const note = typed.trim(); setTyped("");
      push({ id: uid(), type: "user", text: `📎 ${a.name || "Arquivo"}${note ? `: ${note}` : ""}` });
      setBusy(true);
      const before = historyCount();
      try {
        const image_b64 = await new File(a.uri).base64();
        showResult(await api("/v1/photo", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ image_b64, media_type, text: note }) }), false);
      } catch (e: any) { await recover(e, before); }
      finally { setBusy(false); }
    } catch (e: any) { fail(`arquivo: ${e?.message ?? e}`); }
  }

  async function reconnectGoogle() {
    try { await Linking.openURL((await api("/v1/auth/google/link", {}, 15000)).url); }
    catch (e: any) { fail(`Google: ${e?.message ?? e}`); }
  }

  async function moreMenu() {
    const pending = await SecureStore.getItemAsync("pendingMeeting");
    setSheet({ title: base(), items: [
      ["🔌  Testar conexão", testConnection],
      ...(pending ? [["🎙  Reenviar reunião", () => sendMeetingFile(pending)] as [string, () => void]] : []),
      ["🔑  Reconectar Google", reconnectGoogle],
      ["↩️  Trocar servidor", logout],
    ] });
  }

  async function sendText(preset?: string) {
    const text = (preset ?? typed).trim();
    if (!text) return;
    if (busy) return;
    if (!preset) setTyped("");
    setBusy(true);
    push({ id: uid(), type: "user", text });  // aparece na hora
    const before = historyCount();
    try {
      showResult(await api("/v1/message", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
      }), false);
    } catch (e: any) { await recover(e, before); }
    finally { setBusy(false); }
  }

  // ---------- Ações que pedem autorização ----------
  function updateAction(id: string, patch: Partial<Action>) {
    setItems((prev) => prev.map((it) =>
      it.type === "action" && it.action.id === id ? { ...it, action: { ...it.action, ...patch } } : it));
  }

  async function confirmInvite(a: Action) {
    Alert.alert("Enviar convite?", `${a.payload.title}\nPara: ${(a.payload.emails || []).join(", ")}\n\nO Google manda o convite por e-mail.`, [
      { text: "Cancelar", style: "cancel" },
      { text: "Enviar", onPress: async () => {
          updateAction(a.id, { status: "sending" });  // esconde os botões: um toque = um envio
          try {
            await api(`/v1/actions/${a.id}/confirm`, { method: "POST" });
            updateAction(a.id, { status: "sent" });
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
          } catch (e: any) { updateAction(a.id, { status: "pending" }); Alert.alert("Falha ao enviar", e.message); }
        } },
    ]);
  }

  async function openDoc(d: Doc) {
    try {
      // o link assinado vale 1 h; se a mensagem for antiga, pede um novo
      const fresh = (await api(`/v1/documents?q=${encodeURIComponent(d.title)}`, {}, 15000)).documents
        ?.find((x: Doc) => x.document_id === d.document_id);
      await Linking.openURL((fresh || d).url);
    } catch (e: any) { Alert.alert("Documento", e?.message ?? String(e)); }
  }

  async function confirmSend(a: Action) {
    Alert.alert("Enviar e-mail?", `Para: ${a.payload.to}`, [
      { text: "Cancelar", style: "cancel" },
      { text: "Enviar", onPress: async () => {
          try {
            await api(`/v1/actions/${a.id}/edit`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ body: a.payload.body }),
            });
            updateAction(a.id, { status: "sending" });  // esconde os botões: um toque = um envio
            await api(`/v1/actions/${a.id}/confirm`, { method: "POST" });
            updateAction(a.id, { status: "sent" });
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
          } catch (e: any) { updateAction(a.id, { status: "pending" }); Alert.alert("Falha ao enviar", e.message); }
        } },
    ]);
  }

  async function cancel(a: Action) {
    try { await api(`/v1/actions/${a.id}/cancel`, { method: "POST" }); updateAction(a.id, { status: "cancelled" }); }
    catch (e: any) { Alert.alert("Erro", e.message); }
  }

  // ---------- Telas ----------
  if (!configured) {
    return (
      <SafeAreaView edges={["top", "bottom"]} style={[s.flex, { backgroundColor: c.bg }]}>
        <View style={s.setup}>
          <Text style={[s.logo, { color: c.text }]}>Fidus</Text>
          <Text style={{ color: c.sub, marginBottom: 24 }}>Conecte ao seu servidor</Text>
          <TextInput style={[s.input, { color: c.text, backgroundColor: c.card }]} placeholder="https://api.seudominio.com"
            placeholderTextColor={c.sub} autoCapitalize="none" value={server} onChangeText={setServer} />
          <TextInput style={[s.input, { color: c.text, backgroundColor: c.card }]} placeholder="Token do app"
            placeholderTextColor={c.sub} autoCapitalize="none" secureTextEntry value={token} onChangeText={setToken} />
          <Pressable style={s.primary} onPress={async () => {
            const sv = server.trim().replace(/\/$/, ""); const tk = token.trim(); setServer(sv); setToken(tk);
            await SecureStore.setItemAsync("server", sv); await SecureStore.setItemAsync("token", tk);
            setConfigured(true);
          }}><Text style={s.primaryText}>Entrar</Text></Pressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={["top", "bottom"]} style={[s.flex, { backgroundColor: c.bg }]}>
      <KeyboardAvoidingView style={s.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={s.topbar}>
          <View style={{ flex: 1 }}>
            <Text style={[s.header, { color: c.text, paddingHorizontal: 0 }]}>Fidus</Text>
            <Text style={{ color: c.sub, fontSize: 12 }} numberOfLines={1}>{base()}</Text>
          </View>
          <Pressable style={[s.chip, meeting ? { backgroundColor: RED, borderColor: RED } : { borderColor: c.sub }]} onPress={meetingMenu}
            accessibilityLabel="Gravar reunião">
            <Text style={{ color: meeting ? "#fff" : c.text, fontSize: 13, fontWeight: meeting ? "700" : "400" }}>
              {meeting ? `● ${fmtClock(meetSecs)}` : "🎙 Reunião"}</Text></Pressable>
          <Pressable style={[s.chip, { borderColor: c.sub, paddingHorizontal: 12 }]} onPress={moreMenu} accessibilityLabel="Mais opções">
            <Text style={{ color: c.text, fontSize: 13 }}>⋯</Text></Pressable>
        </View>
        <View style={s.tabs}>
          {(["chat", "tasks", "activity"] as const).map((t) => (
            <Pressable key={t} onPress={() => { setTab(t); if (t === "activity") loadActivity(); if (t === "tasks") loadTasks(); }}
              style={[s.tab, tab === t && { borderBottomColor: MINT }]}>
              <Text style={{ color: tab === t ? c.text : c.sub, fontWeight: tab === t ? "700" : "400" }}>
                {t === "chat" ? "Conversa" : t === "tasks" ? "Tarefas" : "Atividade"}</Text>
            </Pressable>
          ))}
        </View>
        {tab === "tasks" ? (
          <View style={s.flex}>
            <View style={[s.row, { paddingHorizontal: 16, paddingTop: 12, gap: 8 }]}>
              <TextInput style={[s.input, s.flex, { color: c.text, backgroundColor: c.card, marginBottom: 0 }]}
                placeholder="Nova tarefa…" placeholderTextColor={c.sub} value={newTask} onChangeText={setNewTask}
                onSubmitEditing={addTaskQuick} returnKeyType="done" />
              <Pressable onPress={addTaskQuick} style={[s.mic, { backgroundColor: NAVY, width: 48, height: 48 }]}>
                <Text style={s.micText}>＋</Text></Pressable>
            </View>
            <FlatList
              data={tasks} keyExtractor={(t) => String(t.id)} contentContainerStyle={{ padding: 16, gap: 8 }}
              refreshing={tasksLoading} onRefresh={loadTasks}
              ListEmptyComponent={<Text style={[s.empty, { color: c.sub }]}>
                {tasksLoading ? "Carregando…" : "Nenhuma tarefa aberta.\nDiga, por exemplo: “cria a tarefa de revisar o contrato até sexta”."}</Text>}
              renderItem={({ item: t }) => (
                <Pressable onLongPress={() => removeTask(t)} style={[s.actCard, { backgroundColor: c.card, paddingVertical: 12 }]}>
                  <Pressable onPress={() => toggleTask(t)} hitSlop={10}
                    style={[s.check, { borderColor: t.priority === "alta" ? RED : c.sub }]} accessibilityLabel="Concluir" />
                  <View style={{ flex: 1 }}>
                    <Text style={{ color: c.text, fontWeight: "600" }}>{t.title}</Text>
                    {(!!t.due || t.priority === "alta") && (
                      <Text style={{ color: t.overdue ? RED : c.sub, fontSize: 12, marginTop: 2 }}>
                        {t.due ? (t.overdue ? `atrasada · era ${fmtDay(t.due)}` : `até ${fmtDay(t.due)}`) : ""}
                        {t.priority === "alta" ? `${t.due ? " · " : ""}prioridade alta` : ""}</Text>)}
                  </View>
                </Pressable>
              )}
            />
          </View>
        ) : tab === "activity" ? (
          <FlatList
            data={acts} keyExtractor={(a) => String(a.id)} contentContainerStyle={{ padding: 16, gap: 10 }}
            refreshing={actsLoading} onRefresh={loadActivity}
            ListHeaderComponent={stats && stats.actions_this_month > 0 ? (
              <View style={[s.statCard, { backgroundColor: NAVY }]}>
                <Text style={{ color: MINT, fontSize: 28, fontWeight: "800" }}>{stats.actions_this_month}</Text>
                <Text style={{ color: "#fff", flex: 1 }}>coisas que o Fidus resolveu por você este mês{"\n"}
                  <Text style={{ color: "#B9C6DD", fontSize: 12 }}>≈ {stats.minutes_saved_estimate >= 60
                    ? `${Math.round(stats.minutes_saved_estimate / 6) / 10} h` : `${stats.minutes_saved_estimate} min`} poupados (estimativa)</Text></Text>
              </View>) : null}
            ListEmptyComponent={<Text style={[s.empty, { color: c.sub }]}>
              {actsLoading ? "Carregando…" : "Nada por aqui ainda.\nTudo o que o Fidus fizer por você aparece nesta lista."}</Text>}
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
                  <Text style={{ color: c.sub, fontSize: 12, marginTop: 2 }}>
                    {LABEL[a.kind] ?? a.kind} · {fmtDate(a.created_at)}</Text>
                </View>
                {a.can_undo && (
                  <Pressable style={[s.chip, { borderColor: c.sub }]} onPress={() => undo(a)}>
                    <Text style={{ color: c.text, fontSize: 12 }}>Desfazer</Text></Pressable>
                )}
              </View>
              );
            }}
          />
        ) : (<>
        <FlatList
          ref={listRef} data={items} keyExtractor={(i) => i.id} contentContainerStyle={{ padding: 16, gap: 10 }}
          keyboardShouldPersistTaps="handled"
          ListFooterComponent={busy ? (
            <View style={[s.bubble, { backgroundColor: c.card, flexDirection: "row", alignItems: "center", gap: 8 }]}>
              <ActivityIndicator color={c.sub} /><Text style={{ color: c.sub }}>Fidus está pensando…</Text>
            </View>) : null}
          ListEmptyComponent={<Text style={[s.empty, { color: c.sub }]}>
            Toque no microfone, fale e toque de novo para enviar.{"\n"}Ex.: “Marca visita técnica dia 12 às 4pm”,{"\n"}“Me lembra de pagar o IVA dia 5”,{"\n"}“Paguei 60 libras de gasolina, HomB” ou{"\n"}📷 mande a foto de um recibo ou documento.{"\n"}{"\n"}🎙 Reunião no topo grava e gera a ata.
          </Text>}
          renderItem={({ item }) => {
            if (item.type === "user")
              return <View style={[s.bubble, s.userBubble]}><Text selectable style={s.userText}>{item.text}</Text></View>;
            if (item.type === "fidus")
              return <View style={[s.bubble, { backgroundColor: c.card }]}><Text selectable style={{ color: c.text }}>{item.text}</Text></View>;
            if (item.type === "upsell") {
              const u = item.up;
              return (
                <View style={[s.draft, { backgroundColor: NAVY, borderColor: MINT }]}>
                  <Text style={{ color: MINT, fontSize: 12, fontWeight: "700", letterSpacing: 0.5 }}>PLANO {u.name.toUpperCase()}</Text>
                  <Text style={{ color: "#fff", fontSize: 22, fontWeight: "800", marginTop: 4 }}>{eur(u.month)}<Text style={{ fontSize: 13, fontWeight: "400", color: "#B9C6DD" }}> /mês · ou {eur(u.year)}/ano</Text></Text>
                  <Text style={{ color: "#DDE5F2", marginTop: 6 }}>Libera {u.feature_label} e mais:</Text>
                  {u.highlights.slice(0, 4).map((h) => <Text key={h} style={{ color: "#fff", marginTop: 3 }}>✓ {h}</Text>)}
                  <View style={[s.row, { marginTop: 12 }]}>
                    <Pressable style={[s.secondary, { borderColor: "#5B6B85" }]} onPress={() => setItems((prev) => prev.filter((x) => x.id !== item.id))}>
                      <Text style={{ color: "#DDE5F2" }}>Agora não</Text></Pressable>
                    <Pressable style={[s.primarySm, { backgroundColor: MINT }]} onPress={() => u.url ? Linking.openURL(u.url)
                      : Alert.alert(`Plano ${u.name}`, "A assinatura pelo app chega em breve. Por enquanto, fale com a gente pelo e-mail de suporte.")}>
                      <Text style={{ color: NAVY, fontWeight: "700" }}>Conhecer o {u.name}</Text></Pressable>
                  </View>
                </View>
              );
            }
            if (item.type === "doc") {
              const d = item.doc;
              return (
                <Pressable onPress={() => openDoc(d)} style={[s.actCard, { backgroundColor: c.card, borderWidth: 1, borderColor: MINT }]}>
                  <Text style={s.actIcon}>📄</Text>
                  <View style={{ flex: 1 }}>
                    <Text style={{ color: c.text, fontWeight: "600" }}>{d.title}</Text>
                    {!!d.expires_on && <Text style={{ color: c.sub, fontSize: 12 }}>vence {fmtDay(d.expires_on)}/{d.expires_on.slice(0, 4)}</Text>}
                  </View>
                  <Text style={{ color: MINT, fontWeight: "700" }}>Abrir</Text>
                </Pressable>
              );
            }
            const a = item.action;
            if (a.kind === "calendar_invite") {
              return (
                <View style={[s.draft, { backgroundColor: c.card, borderColor: MINT }]}>
                  <Text style={[s.draftLabel, { color: c.sub }]}>Convite · {a.status === "pending" ? "aguardando você" : a.status === "sending" ? "enviando…" : a.status === "sent" ? "enviado ✓" : "cancelado"}</Text>
                  <Text style={{ color: c.text, fontWeight: "600" }}>{a.payload.title}</Text>
                  {!!a.payload.start && <Text style={{ color: c.sub }}>{fmtDate(a.payload.start)}</Text>}
                  <Text style={{ color: c.text, marginVertical: 6 }}>Para: {(a.payload.emails || []).join(", ")}</Text>
                  {a.status === "pending" && (
                    <View style={s.row}>
                      <Pressable style={[s.secondary, { borderColor: c.sub }]} onPress={() => cancel(a)}>
                        <Text style={{ color: c.text }}>Cancelar</Text></Pressable>
                      <Pressable style={s.primarySm} onPress={() => confirmInvite(a)}>
                        <Text style={s.primaryText}>Enviar convite</Text></Pressable>
                    </View>
                  )}
                </View>
              );
            }
            return (
              <View style={[s.draft, { backgroundColor: c.card, borderColor: MINT }]}>
                <Text style={[s.draftLabel, { color: c.sub }]}>Rascunho de e-mail · {a.status === "pending" ? "aguardando você" : a.status === "sending" ? "enviando…" : a.status === "sent" ? "enviado ✓" : "cancelado"}</Text>
                <Text style={{ color: c.text, fontWeight: "600" }}>Para: {a.payload.to}</Text>
                <Text style={{ color: c.text, marginBottom: 8 }}>{a.payload.subject}</Text>
                <TextInput multiline editable={a.status === "pending"} value={a.payload.body}
                  onChangeText={(t) => updateAction(a.id, { payload: { ...a.payload, body: t } })}
                  style={[s.draftBody, { color: c.text, borderColor: c.sub }]} />
                {a.status === "pending" && (
                  <View style={s.row}>
                    <Pressable style={[s.secondary, { borderColor: c.sub }]} onPress={() => cancel(a)}>
                      <Text style={{ color: c.text }}>Cancelar</Text></Pressable>
                    <Pressable style={s.primarySm} onPress={() => confirmSend(a)}>
                      <Text style={s.primaryText}>Enviar</Text></Pressable>
                  </View>
                )}
              </View>
            );
          }}
        />
        {recording && <Text style={[s.empty, { color: MINT, marginTop: 0 }]}>● Gravando… toque de novo para enviar</Text>}
        {meeting && (
          <Pressable onPress={finishMeeting} style={[s.meetBar, { backgroundColor: c.card, borderColor: RED }]}>
            <Text style={{ color: RED, fontWeight: "800" }}>● REC {fmtClock(meetSecs)}</Text>
            <Text style={{ color: c.text, flex: 1 }}>Gravando a reunião. Mantenha o Fidus aberto.</Text>
            <Text style={{ color: c.text, fontWeight: "700" }}>Encerrar</Text>
          </Pressable>
        )}
        {!meeting && !recording && typed.length === 0 && kb === 0 && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} keyboardShouldPersistTaps="handled"
            contentContainerStyle={{ paddingHorizontal: 12, gap: 8 }} style={{ flexGrow: 0 }}>
            {SUGGESTIONS.map(([label, q]) => (
              <Pressable key={label} disabled={busy} onPress={() => sendText(q)} style={[s.chip, { borderColor: c.sub, backgroundColor: c.card }]}>
                <Text style={{ color: c.text, fontSize: 13 }}>{label}</Text></Pressable>
            ))}
          </ScrollView>
        )}
        <View style={[s.bottom, Platform.OS === "android" && kb > 0 ? { marginBottom: Math.max(kb - insets.bottom, 0) + 56 } : null]}>
          <Pressable onPress={photoMenu} disabled={busy || recording} accessibilityLabel="Enviar foto"
            style={[s.cam, { backgroundColor: c.card }]}>
            <Text style={{ fontSize: 22 }}>📷</Text>
          </Pressable>
          <TextInput style={[s.input, s.flex, { color: c.text, backgroundColor: c.card, marginBottom: 0 }]}
            placeholder="Escreva ou toque no microfone…" multiline blurOnSubmit placeholderTextColor={c.sub} value={typed}
            onChangeText={setTyped} onSubmitEditing={() => sendText()} returnKeyType="send" />
          {typed.trim().length > 0 ? (
            <Pressable onPress={() => sendText()} disabled={busy} accessibilityLabel="Enviar"
              style={[s.mic, { backgroundColor: busy ? c.sub : NAVY }]}>
              <Text style={s.micText}>➤</Text>
            </Pressable>
          ) : (
            <Pressable onPress={toggleRec} disabled={busy || meeting} accessibilityLabel="Gravar"
              style={[s.mic, { backgroundColor: recording ? MINT : busy ? c.sub : NAVY, transform: [{ scale: recording ? 1.15 : 1 }] }]}>
              <Text style={s.micText}>{recording ? "■" : "🎙"}</Text>
            </Pressable>
          )}
        </View>
        </>)}
      </KeyboardAvoidingView>
      <Modal visible={!!sheet} transparent animationType="slide" onRequestClose={() => setSheet(null)}>
        <Pressable style={s.sheetBg} onPress={() => setSheet(null)}>
          <View style={[s.sheet, { backgroundColor: c.card, paddingBottom: 16 + insets.bottom }]}>
            <Text style={{ color: c.sub, marginBottom: 8 }} numberOfLines={1}>{sheet?.title}</Text>
            {(sheet?.items || []).map(([label, fn]) => (
              <Pressable key={label} style={[s.sheetBtn, { borderColor: c.sub + "55" }]} onPress={() => { setSheet(null); setTimeout(fn, 250); }}>
                <Text style={{ color: c.text, fontSize: 17 }}>{label}</Text></Pressable>
            ))}
            <Pressable style={[s.sheetBtn, { borderBottomWidth: 0 }]} onPress={() => setSheet(null)}>
              <Text style={{ color: c.sub, fontSize: 17 }}>Cancelar</Text></Pressable>
          </View>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  meetBar: { flexDirection: "row", alignItems: "center", gap: 10, marginHorizontal: 12, marginBottom: 8, padding: 12, borderRadius: 12, borderWidth: 1.5 },
  sheetBg: { flex: 1, backgroundColor: "#0008", justifyContent: "flex-end" },
  sheet: { borderTopLeftRadius: 18, borderTopRightRadius: 18, padding: 16 },
  sheetBtn: { paddingVertical: 16, borderBottomWidth: StyleSheet.hairlineWidth },
  flex: { flex: 1 },
  setup: { flex: 1, justifyContent: "center", padding: 24 },
  logo: { fontSize: 40, fontWeight: "700", marginBottom: 4 },
  tabs: { flexDirection: "row", paddingHorizontal: 16, marginTop: 8, gap: 16 },
  tab: { paddingVertical: 8, borderBottomWidth: 2, borderBottomColor: "transparent" },
  actCard: { flexDirection: "row", alignItems: "center", gap: 12, borderRadius: 14, padding: 14 },
  actIcon: { fontSize: 22 },
  check: { width: 24, height: 24, borderRadius: 12, borderWidth: 2 },
  statCard: { flexDirection: "row", alignItems: "center", gap: 14, borderRadius: 14, padding: 16, marginBottom: 6 },
  pill: { alignSelf: "flex-start", borderWidth: 1, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2, marginBottom: 4 },
  topbar: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 16, paddingTop: 8 },
  chip: { borderWidth: 1, borderRadius: 999, paddingVertical: 6, paddingHorizontal: 10 },
  sendBtn: { backgroundColor: NAVY, borderRadius: 12, paddingVertical: 12, paddingHorizontal: 14 },
  header: { fontSize: 22, fontWeight: "700", paddingHorizontal: 16, paddingTop: 8 },
  empty: { textAlign: "center", marginTop: 80, lineHeight: 22 },
  input: { borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, marginBottom: 12, fontSize: 16 },
  primary: { backgroundColor: NAVY, borderRadius: 12, padding: 14, alignItems: "center" },
  primarySm: { backgroundColor: NAVY, borderRadius: 10, paddingVertical: 10, paddingHorizontal: 20 },
  primaryText: { color: "#fff", fontWeight: "600" },
  secondary: { borderWidth: 1, borderRadius: 10, paddingVertical: 10, paddingHorizontal: 16 },
  bubble: { borderRadius: 14, padding: 12, maxWidth: "85%" },
  userBubble: { backgroundColor: NAVY, alignSelf: "flex-end" },
  userText: { color: "#fff" },
  draft: { borderRadius: 14, padding: 14, borderWidth: 1.5 },
  draftLabel: { fontSize: 12, marginBottom: 6 },
  draftBody: { borderWidth: StyleSheet.hairlineWidth, borderRadius: 8, padding: 10, minHeight: 90, marginBottom: 10 },
  row: { flexDirection: "row", justifyContent: "flex-end", gap: 10 },
  bottom: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12 },
  cam: { width: 48, height: 48, borderRadius: 24, alignItems: "center", justifyContent: "center" },
  mic: { width: 64, height: 64, borderRadius: 32, alignItems: "center", justifyContent: "center" },
  micText: { fontSize: 26, color: "#fff" },
});
