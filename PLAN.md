# X-Agent — Otonom, Algoritma-Bilinçli X (Twitter) Menajeri

> **Tek cümle:** Senin **gerçek** X hesabını, X'in açık kaynak "For You" sıralama mantığını bilen,
> senin yerine X'te gezip öğrenen ve günlük içerik üretip yayınlayan **tam otonom** bir yapay zekâ menajeri.

Bu, sahte/kurgusal hesap **değildir**. Tek otantik hesabı otomasyonla yönetmek X ToS'una aykırı değildir
(X/Grok bunu zaten sunuyor). Yasak olan koordineli sahte hesaplardır; biz onu yapmıyoruz.

---

## 1. Kilitlenmiş Kararlar

| Konu | Karar |
|---|---|
| Hesap | Kullanıcının **tek, gerçek** X hesabı |
| Otonomi | **Tam otonom** (önce 1 hafta *shadow mode*, sonra canlı) |
| Kapsam | **8 bileşenin tamamı**, fazlara bölünmüş |
| Beyin (LLM) | **Gemini API** (`gemini-2.5-flash` yüksek hacim, `gemini-2.5-pro` derin analiz, Flash multimodal = vision) |
| Okuma / Analiz | **Tarayıcı-ajanı** (Playwright + kullanıcının kalıcı Chrome profili) — *sadece gözlemler* |
| Yazma / Yayın | **Free X API v2** (temiz, ToS-onaylı kanal) |
| Çalışma yeri | **Kullanıcının kendi makinesi** (ev IP'si, gerçek profil → en düşük bot-tespit riski) |
| Maliyet | **0 ₺** hedef: Free X API (yazma) + Gemini ücretsiz katman (beyin) + yerel tarayıcı (okuma) |
| Oracle | Repodaki `weighted_scorer` ağırlık mantığı + Gemini-yargıç + kullanıcının kendi verisiyle kalibrasyon |
| Dil / Depo | **Python**, **SQLite**, **APScheduler** |

---

## 2. Mimari

```
  KULLANICININ MAKİNESİNDE çalışan tek Python uygulaması
  ┌──────────────────────────────────────────────────────────────────┐
  │  ⑧ SHOWRUNNER (Orkestratör)                                        │
  │     günlük döngüyü kurar · oturumları zamanlar · modülleri çağırır │
  │                                                                    │
  │  ALGI KATMANI (OKU — tarayıcı)         BEYİN (KARAR/ÜRET — Gemini)  │
  │  ┌───────────────────────────┐         ┌────────────────────────┐ │
  │  │ Playwright + Chrome profil │         │ ① Brand Bible (config) │ │
  │  │  • observe_self  (kendi    │  veri   │ ② Content Engine       │ │
  │  │    metrik + Analytics)     │────────▶│ ③ Oracle (banger skor) │ │
  │  │  • observe_niche (rakip/   │         │ ⑦ Safety Guard         │ │
  │  │    feed gözlemi)           │         │ ⑧ Strategist (takvim)  │ │
  │  │  • ⑤ trends (trend radar)  │         └───────────┬────────────┘ │
  │  └───────────────┬───────────┘                     │ en iyi taslak │
  │                  │                                  ▼               │
  │   ⑥ FEEDBACK     │                       ┌────────────────────┐    │
  │   (metrik→tahmin │◀──────────────────────│ ACTION: Free X API │    │
  │    kıyas→kalibre)│      yayınlanan post   │  → POST / REPLY    │    │
  │                  └────────────────────────└────────────────────┘   │
  └──────────────────────────────────────────────────────────────────┘
        OKU = tarayıcı (sadece bakar)        YAZ = Free API (temiz kanal)
```

**Veri akışı (tek günlük döngü):**
`Gözlem (tarayıcı oku) → Brand Bible + trend → Content Engine N taslak → Oracle skorla →
Safety Guard ele → eşik üstündeyse en iyiyi Free API ile yayınla → (sonra) metrik topla →
Feedback kıyas → Oracle & strateji kalibrasyonu.`

---

## 3. Sekiz Bileşen — Sorumluluklar

| # | Bileşen | Girdi | Çıktı | Görev |
|---|---------|-------|-------|-------|
| ① | **Brand Bible** | Kullanıcı (niş, ton, temalar, no-go, hedefler) | yapılandırılmış profil (YAML) | Tüm modüllerin uyduğu "anayasa"; Feedback ile evrilir |
| ② | **Content Engine** | Brand Bible + günün trendi + geçmiş öğrenmeler | N aday taslak (çoklu format) | Senin sesinde içerik: thread, hot-take, reply, soru, meme-fikri |
| ③ | **Oracle** | aday taslaklar | banger skoru + tahmini erişim + güven | Repo ağırlıkları + Gemini-yargıç ile her taslağı puanlar, en iyiyi seçer |
| ④ | **Engagement Strategy** | niş gözlemi (tarayıcı) | reply hedefleri | Büyük/ilgili hesaplara stratejik reply → ağ-dışı (OON) keşif |
| ⑤ | **Trend Radar** | tarayıcı (Explore/trendler) | güncel trend listesi + niş-uyumu | Tazelik penceresinde uygun trende binmeyi önerir |
| ⑥ | **Feedback Loop** | yayın sonrası metrikler | kalibrasyon güncellemeleri | Tahmin↔gerçek kıyası; Oracle ve Brand stratejisini iyileştirir |
| ⑦ | **Safety Guard** | aday taslak | geç/ele kararı + gerekçe | Marka-güvenliği + negatif-sinyal (mute/report) riskini eler |
| ⑧ | **Showrunner / Strategist** | hepsi | günlük plan + editoryal takvim | Seri/format planı, kampanya yayları, döngü orkestrasyonu |

---

## 4. Oracle Tasarımı (sistemin kalbi)

X'in gerçek Phoenix transformer'ını çalıştıramayız (3 GB model + her izleyicinin geçmişi + global corpus
gerekir). Bunun yerine **algoritmanın ağırlık mantığını** + bir **LLM-yargıç**ı + **senin verinle kalibrasyon**u
birleştiriyoruz:

**Aşama A — Heuristik (veri yokken, 1. günden çalışır):**
1. `weighted_scorer.rs`'teki ödüllendirilen sinyaller: favorite, **reply**, retweet, photo_expand, click,
   **profile_click**, video-quality-view, **share / share_via_dm / share_via_copy_link**, dwell, quote,
   quoted_click, dwell_time, **follow_author**; cezalar: not_interested, mute, block, report.
2. Gemini'ye taslağı verip her sinyal ekseni için 0–1 olasılık/şiddet puanı aldırırız (LLM = sinyal tahmincisi).
3. Bu eksenleri **repodaki gerçek ağırlıklarla** birleştirip `weighted_score` üretiriz → "banger skoru".
   > Not: Bazı ağırlık sabitleri repoda ayrı bir `params` modülünde; mevcut değilse X'in bilinen göreli
   > önemini (reply ≫ like, "birine göstermek için paylaşım" ağır) başlangıç değeri alır, kalibrasyon düzeltir.

**Aşama B — Kalibrasyon (veri biriktikçe):**
- DB'deki gerçek sonuçlar (views, like, RT, reply, bookmark…) ile Gemini'nin tahmin eksenlerini eşleştiren
  **hafif bir regresör** (scikit-learn lineer/lojistik ya da format/konu bazlı bias-düzeltme) eğitilir.
- Böylece LLM-yargıç **senin kitlene** kalibre olur; Oracle zamanla "senin hesabın için akıllanan banger-dedektörü"ne döner.

**Çıktı:** `banger_score`, `tahmini_views_aralığı`, `güven`. Showrunner eşik üstü + en yüksek skorlu taslağı
seçer; eşik altıysa **yayınlamaz** (otonomi güvenlik kemeri).

---

## 5. Tarayıcı-Ajanı (Algı Katmanı)

- **Motor:** Playwright (Python), `launch_persistent_context` ile **kalıcı Chrome profili** (`chrome_profile/`)
  → cookie saklı, tekrar login yok, 2FA bir kez.
- **Yöntem:** Önce **DOM** (hızlı, sayıları net çeker). Seçiciler tek dosyada (`selectors.py`) toplanır →
  X arayüzü değişince tek yerden bakım. **Vision yedeği:** DOM tıkanırsa ekran görüntüsü Gemini-Flash'a verilir.
- **Okunan veriler:**
  - `observe_self`: kendi tweet metrikleri (views/like/RT/reply/quote/bookmark) + Analytics (impression, profil
    ziyareti, link-tık, takip kazanımı, OON kırılımı — *hepsi ücretsiz, senin panelinde*).
  - `observe_niche`: nişindeki/takip ettiğin hesapların ne attığı ve ne tuttuğu (view/like oranları).
  - `trends`: Explore/trend listesi + niş-uyum filtresi.
- **Davranış kuralları (bot-tespiti azaltma):** insan-hızı tıklama/scroll, **günde 1–3 kısa oturum**, 7/24
  değil, rastgele jitter, sadece kendi + hafif niş verisi (kitlesel scraping yok).

---

## 6. Gemini Entegrasyonu

| Kullanım | Model | Gerekçe |
|---|---|---|
| Taslak üretimi (yüksek hacim) | `gemini-2.5-flash` | Hızlı + ücretsiz katmanda bol kota |
| Oracle sinyal-puanlama | `gemini-2.5-flash` | Çok sayıda taslak × eksen |
| Niş gözlem özeti / sınıflandırma | `gemini-2.5-flash` | Ucuz, hacimli |
| Vision yedeği (ekran görüntüsü) | `gemini-2.5-flash` (multimodal) | Aynı sağlayıcı |
| Haftalık strateji / derin analiz | `gemini-2.5-pro` | Az sayıda, kaliteli akıl yürütme |

- **SDK:** `google-genai`. Anahtar `.env` içinde `GEMINI_API_KEY`.
- **Maliyet kontrolü:** İstek başına token bütçesi, önbellekleme (aynı trend/gözlem tekrar yollanmaz),
  ücretsiz katman RPM/RPD limitlerine saygılı throttle.
- Prompt şablonları `src/llm/prompts.py` içinde versiyonlanır (Brand Bible enjekte edilir).

---

## 7. Otonom Döngü ve Zamanlama (APScheduler)

- **Sabah gözlem oturumu:** tarayıcı → kendi metrikler + trend + niş → DB.
- **Üretim/yayın oturum(lar)ı (günde N, N kullanıcı/Oracle önerir):** Content → Oracle → Safety →
  eşik üstüyse Free API ile yayınla.
- **Akşam feedback oturumu:** gün içi yayınların metriklerini topla → tahmin↔gerçek kıyas → kalibrasyon.
- **Haftalık strateji (pro):** editoryal takvim + Brand Bible güncellemesi.
- **Kontrol:** Tek `main.py` entry; oturumlar log'lanır; her oturum idempotent ve kurtarılabilir.

---

## 8. Güvenlik Kemerleri (tam otonomi için zorunlu)

- **Shadow mode (ilk hafta):** hiçbir şey yayınlanmaz; taslak+skor DB'ye yazılır, kullanıcı inceler → sonra canlı.
- **Günlük post tavanı** + minimum aralık (author-diversity sönümü ve spam filtresinden kaçınma).
- **Kill-switch:** tek komut/dosya bayrağıyla tüm yayını durdur.
- **Oracle güven eşiği:** düşük güven → yayınlama.
- **Safety Guard sert filtreleri:** marka no-go + negatif-sinyal riski + PTOS-tarzı içerik kontrolü.
- **İnsan-hızı pacing**, gerçek profil/IP, 7/24 değil.
- **Tam denetim izi:** her karar (taslaklar, skorlar, neden seçildi/elendi) DB+log'da.

---

## 9. Veri Modeli (SQLite — `data/xagent.db`)

- `drafts(id, created_at, format, topic, text, oracle_score, predicted_views, confidence, safety_ok, status)`
- `posts(id, x_post_id, draft_id, published_at, text)`
- `metrics(id, post_id, captured_at, views, likes, retweets, replies, quotes, bookmarks, profile_clicks, link_clicks, follows, oon_impressions)`
- `observations(id, captured_at, kind, payload_json)`   ← niş/trend gözlemleri
- `trends(id, captured_at, name, volume, niche_fit)`
- `learnings(id, updated_at, key, value_json)`            ← kalibrasyon katsayıları, "neyin tuttuğu"
- `sessions(id, started_at, type, status, notes)`         ← denetim/oturum izi

---

## 10. Proje Klasör Yapısı

```
x-agent/
├── PLAN.md                  # bu doküman
├── README.md
├── requirements.txt
├── .env.example             # GEMINI_API_KEY, X_API_* (gerçeği .env, git'e girmez)
├── config/
│   ├── brand_bible.yaml      # niş, ton, temalar, no-go, hedefler
│   └── settings.yaml         # cadence, caps, eşikler, model adları, shadow_mode
├── data/xagent.db
├── chrome_profile/           # kalıcı Playwright profili (git-ignore)
├── logs/
└── src/
    ├── main.py               # entrypoint + scheduler
    ├── showrunner.py         # ⑧ orkestratör
    ├── config.py             # config + brand bible yükleyici
    ├── db.py                 # SQLite katmanı + şema
    ├── llm/{gemini.py, prompts.py}
    ├── perception/{browser.py, selectors.py, observe_self.py, observe_niche.py, trends.py}
    ├── brain/{content_engine.py, oracle.py, safety_guard.py, strategist.py}
    ├── action/{publisher.py}            # Free X API (tweepy/OAuth)
    ├── feedback/{learner.py}
    └── oracle_weights/{weights.py}      # repo ağırlıklarının Python karşılığı
```

---

## 11. Faz Planı (kabul kriterleriyle)

**P0 — İskelet & Erişim**
- Klasör yapısı, `requirements.txt`, `.env`, `config/*`, SQLite şeması.
- Playwright kalıcı profil → X'e bir kez login (2FA dahil) → oturum saklanıyor.
- Free X API ile **tek otonom test-post** ("hello world").
- ✅ Kabul: ajan login olabiliyor, kendi profilini açabiliyor; API ile 1 post atabiliyor; DB kuruldu.

**P1 — Algı Katmanı**
- `observe_self` + `observe_niche` + `trends`: tarayıcıdan veriyi çekip `metrics/observations/trends`'e yazıyor.
- ✅ Kabul: bir gözlem oturumu kendi son N tweet metriğini ve güncel trendleri DB'ye doğru yazıyor.

**P2 — Üretim + Oracle (otonom çekirdek)**
- Content Engine (Gemini) N taslak → Oracle (Aşama A) skorlar → Safety Guard eler → en iyi taslak.
- **Shadow mode:** seçilen taslak yayınlanmaz, DB'ye "yayınlanacaktı" diye işaretlenir.
- ✅ Kabul: tek komutla uçtan uca çekirdek çalışıyor; günlük en iyi taslak + skor + gerekçe üretiliyor.

**P3 — Feedback + Öğrenme + Canlı**
- Yayın açılır (shadow→live), `learner` tahmin↔gerçek kıyasını yapar, Oracle Aşama B kalibrasyonu devreye girer.
- Engagement Strategy (④) reply hedefleri üretir.
- ✅ Kabul: yayınlanan postların metriği toplanıyor, Oracle katsayıları güncelleniyor, isabet artıyor.

**P4 — Showrunner + Tam Otonomi**
- Strategist editoryal takvim + seri/format; çoklu günlük döngü; tüm güvenlik kemerleri aktif.
- ✅ Kabul: sistem gün boyu insan müdahalesiz, güvenli sınırlar içinde planlıyor-üretiyor-yayınlıyor-öğreniyor.

**P5 — Sağlamlaştırma**
- Selector kırılma izleme + vision-yedek, hata kurtarma, raporlama paneli (CLI/HTML özet), maliyet/throttle ayarı.

---

## 12. Riskler ve Azaltma

| Risk | Azaltma |
|---|---|
| Scraping ToS-grisi / askı | Kendi makine/IP, insan-hızı, 7/24 değil, sadece kendi+hafif niş verisi, yayın temiz API'de |
| X arayüzü değişimi → scraper kırılır | Seçiciler tek dosyada; vision-yedek; kırılma testi/alarmı |
| Oracle isabetsizliği (soğuk başlangıç) | Aşama A heuristik + hızlı Aşama B kalibrasyonu; düşük güvende yayınlama |
| Gemini ücretsiz limit | Throttle, önbellek, Flash-öncelik, Pro'yu sadece haftalık |
| Otonom hatalı yayın | Shadow-mode başlangıç, Safety Guard, günlük cap, kill-switch, denetim izi |

---

## 13. Başlamak için kullanıcıdan gerekenler

1. **Brand Bible girdileri:** hesabın ana konusu/nişi, ses tonu, paylaşmak istediğin tema(lar), **no-go** konular,
   hedef (takipçi mi, etkileşim mi, otorite mi), günlük post sayısı tercihi.
2. **Gemini API anahtarı** (ücretsiz katman) → `.env`.
3. **Free X API anahtarları** (yazma için) → `.env`.
4. Onay: P0'dan başlayalım mı?
```
