/*
 * Il renderer dei grafici di Progressive — l'unico JavaScript del progetto.
 *
 * «Niente JavaScript applicativo» (#21) ha **una** eccezione, ed è Chart.js.
 * Questo file è ciò che serve per usarla, ed è scritto perché resti l'unico:
 * non sa niente di volume, di settimane né di gruppi muscolari. Cerca i canvas
 * con `data-grafico`, legge il payload che la view ha messo nella pagina con
 * `{{ ... |json_script:"..." }}` e disegna quello che il payload dichiara.
 *
 * Il payload è **dichiarativo** e porta con sé il tipo di figura:
 *
 *     {"tipo": "line", "etichette": [...], "valori": [...],
 *      "unita": "kg", "serie": "Volume settimanale"}
 *
 * È la ragione per cui il terzo grafico (A3, la progressione del carico) non
 * dovrà toccare questo file: aggiunge un canvas e un `json_script`, e basta.
 *
 * NESSUN `fetch`, e nessun endpoint JSON dietro. I dati sono già nel documento
 * che il server ha reso: senza HTMX un endpoint sarebbe una seconda superficie
 * di viste da scrivere, testare e proteggere, per mostrare gli stessi numeri
 * che la pagina ha già in mano (`docs/spec/04-analisi.md`, §I grafici).
 */
(function () {
  "use strict";

  // I token di `progressive.css`, letti dal CSS e non ricopiati qui: il tema è
  // definito in un posto solo, e un grafico che si scolpisce i colori addosso
  // sarebbe la stessa divergenza silenziosa del volume scritto due volte.
  function token(nome, ripiego) {
    var valore = getComputedStyle(document.documentElement)
      .getPropertyValue(nome)
      .trim();
    return valore || ripiego;
  }

  function disegna(canvas) {
    var contenitore = document.getElementById(canvas.dataset.grafico);
    if (!contenitore) {
      return;
    }
    var dati = JSON.parse(contenitore.textContent);

    var volt = token("--volt", "#C9FF3D");
    var t2 = token("--t2", "#9DA3AC");
    var t3 = token("--t3", "#697079");
    var linea = token("--line", "rgba(255,255,255,.08)");

    new Chart(canvas, {
      type: dati.tipo,
      data: {
        labels: dati.etichette,
        datasets: [
          {
            label: dati.serie,
            data: dati.valori,
            borderColor: volt,
            backgroundColor: dati.tipo === "line" ? "rgba(201,255,61,.12)" : volt,
            borderWidth: 2,
            fill: dati.tipo === "line",
            tension: 0.25,
            pointRadius: 3,
            pointBackgroundColor: volt,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        // La legenda direbbe una cosa sola, che il titolo del riquadro dice
        // già: una figura con un dataset solo non ha niente da distinguere.
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (contesto) {
                return contesto.parsed.y.toLocaleString("it-IT") + " " + dati.unita;
              },
            },
          },
        },
        scales: {
          x: { ticks: { color: t3 }, grid: { display: false } },
          y: {
            // Da zero e non dal minimo: su un asse tagliato una settimana da
            // 9.000 kg accanto a una da 10.000 sembra un crollo, ed è
            // esattamente la lettura sbagliata che questa pagina deve evitare.
            beginAtZero: true,
            ticks: { color: t3 },
            grid: { color: linea },
            border: { color: t2 },
          },
        },
      },
    });
  }

  document.querySelectorAll("canvas[data-grafico]").forEach(disegna);
})();
