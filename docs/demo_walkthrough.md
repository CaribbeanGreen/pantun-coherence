# Semak Pantun — demo walkthrough script (about 5–6 minutes)

Four parts, four presenters. Each part is about 75–90 seconds when spoken.
Style: B1–B2, direct, Malay-English mix. Lines in *[brackets]* are actions on screen, not spoken.
Site: **pantun.aimanjamal.com**. The owner's settings are not part of this demo.

Before you start: log in to each account in its own browser tab (Murid, Cikgu, Penyelidik), so no one waits for a
login on stage.

---

## Part 1 · Murid (Presenter 1)

*[Open the Murid page. Point to the BM / EN switch, top right.]*

Okay, first, the **Murid** side. Ini apa yang budak sekolah nampak bila diorang buka Semak Pantun. Nampak tak
button kecil BM / EN kat atas ni? Satu klik je, the whole app tukar language, so murid boleh pilih yang dia selesa.

*[Click "Pisang emas", then "Semak Pantun Saya".]*

Murid tulis empat baris: dua baris pembayang, dua baris maksud. Kalau takde idea, just tekan satu contoh.
Then tekan **Semak Pantun Saya**, and dalam beberapa saat, keluar tiga dial. **Bunyi** checks the rhyme, a-b-a-b.
**Peraturan** checks the form, macam empat baris dan lapan hingga dua belas suku kata. **Makna** pula is the
interesting one, because it tries to measure whether the pembayang actually prepares the maksud.

*[Scroll to "Apa yang anda buat dengan baik" and "Petua".]*

Notice something: kita tak pernah cakap "gagal". Pujian dulu, then satu petua je, so budak tak rasa down.
Kalau murid rasa computer salah, dia tekan **Saya tidak setuju**, and the question goes straight to his own cikgu.

*[Open "Belajar Pantun", then "Sejarah Saya".]*

**Belajar Pantun** explains the theory dengan contoh yang simple. **Sejarah Saya** keeps every pantun he checked,
plus jawapan cikgu. And kalau confused, tekan **Cara guna**: ada video and a guided tour, even on phone.

---

## Part 2 · Cikgu (Presenter 2)

*[Switch to the Cikgu tab. The Papan pemuka is open.]*

Now jom tengok side **Cikgu**. Bila cikgu log masuk, dia terus nampak **Papan pemuka**: berapa kelas, berapa murid,
and berapa pertanyaan yang tengah tunggu jawapan. Simple, satu skrin je.

*[Open "Kod kelas & murid", create a class.]*

Step pertama, cikgu cipta kelas. The system bagi satu **kod kelas**, contohnya K7QM2X. Cikgu share kod ni, and
murid guna kod tu masa daftar, so they automatically masuk kelas yang betul.

*[Open "Kelas saya", press "Guna kelas contoh".]*

Ni bahagian yang paling jimat masa. Cikgu upload satu fail CSV dengan pantun satu kelas, and the system checks
semua sekali gus. Instead of reading thirty pantun one by one, cikgu dapat **senarai kerja**, with the ones that
need attention di atas.

*[Pick one row. Show the three buttons.]*

For each pantun, cikgu ada tiga pilihan: **Setuju** dengan sistem, **Ubah keputusan**, atau **Hantar kepada pakar**
kalau dia betul-betul tak pasti. Every decision is recorded, so nothing hilang.

*[Open "Semakan", then "Laporan".]*

Dekat **Semakan**, cikgu jawab soalan "saya tidak setuju" daripada murid. And **Laporan** gives a quick chart,
plus export CSV atau PDF untuk rekod sekolah. Bottom line: the system helps, tapi cikgu yang buat keputusan akhir.

---

## Part 3 · Cikgu + Penguji (Presenter 3)

*[Still logged in as Cikgu, open "Borang Penguji".]*

Okay, part ketiga. Before kita launch untuk ramai orang, kita perlukan feedback yang betul, bukan sekadar
"nampak okay". So kita buat **Borang Penguji**. A cikgu, or a friend helping us, can test the whole site
in about twenty minutes.

*[Show section 1 and 2.]*

Bahagian satu, sikit info pasal penguji: background, device, browser. Bahagian dua is a list of real tasks,
contohnya "cipta satu kelas" or "hantar tiga baris sahaja". For each one, penguji tandakan **Berjaya**,
**Ada masalah**, **Gagal** atau **Langkau**, and kalau ada masalah, dia tulis apa yang jadi.

*[Show section 3: check one pantun, then choose the answers.]*

Bahagian tiga is the smart part. Penguji semak at least lima pantun, then he tells us his own opinion: adakah
pembayang dan maksud sepadan, and is our Makna score terlalu rendah, tepat, or terlalu tinggi? With enough answers,
we can see whether our score agrees with real people, which is exactly what a measurement study needs.

*[Show section 4, then "Hantar borang".]*

Last sekali, star rating and a few comments, then **Hantar borang**. Siap. Even the form itself works in BM and EN.

---

## Part 4 · Penyelidik & Pakar (Presenter 4)

*[Switch to the Penyelidik tab. "Analisis pantun" is open.]*

Finally, the **Penyelidik & Pakar** side. This page is for people who want to see every number, no hiding.

*[Pick an example, press "Analisis".]*

Kita paste satu pantun and tekan **Analisis**. Here you can see the result for each of the five embedding models,
macam LaBSE and e5, with the cosine score, the percentile, and the calibrated p(real). The chart shows where this
pantun sits compared to real pantun and random pairings from our corpus of almost eleven thousand pantun.

*[Point to "Penilaian pakar" on the right.]*

On the right, pakar boleh bagi rating satu hingga lima: how strongly does the pembayang prepare the maksud?
Dia pilih jenis kaitan, contohnya gema bunyi or kiasan, and these ratings become our ground truth.

*[Open "Barisan pakar", then "Dapatan".]*

**Barisan pakar** is where the difficult cases from cikgu land. And **Dapatan** shows what we found, honestly.
Rhyme is easy for the computer: AUC 0.99. But the meaning link? The best model only reaches about 0.60. Maksudnya,
computer still can't really understand kiasan.

*[Open "Kaedah".]*

**Kaedah** explains every step so anyone can repeat our work. To be clear, our score is not a judgement of literary
quality. It's a helper for murid, cikgu and pakar, and the final say always stays with humans. Terima kasih!
