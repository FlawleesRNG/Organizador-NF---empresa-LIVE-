document.addEventListener("DOMContentLoaded", () => {
    for (const alert of document.querySelectorAll(".alert.success")) {
        setTimeout(() => alert.classList.add("fade"), 6000);
    }

    const lista = document.getElementById("processamentos-lista");
    if (lista) {
        setInterval(async () => {
            try {
                const resp = await fetch("/api/dashboard/processamentos", { cache: "no-store" });
                if (!resp.ok) return;
                const data = await resp.json();
                const graph = document.getElementById("graph-status");
                if (graph && data.graph) graph.textContent = data.graph.mensagem;
                lista.innerHTML = renderProcessamentos(data.processamentos || []);
            } catch (_err) {
                // O proximo ciclo tenta novamente sem interromper a tela.
            }
        }, 25000);
    }
});

function badgeClass(value) {
    return String(value || "").toLowerCase().replaceAll(" ", "-");
}

function fmt(value) {
    return value || "-";
}

function renderProcessamentos(items) {
    if (!items.length) {
        return '<div class="table-wrap"><p class="empty">Nenhum processamento da caixa compartilhada registrado ainda.</p></div>';
    }
    return items.map((item) => {
        let comparativo = {};
        try { comparativo = JSON.parse(item.comparativo_json || "{}"); } catch (_err) {}
        const linhas = (comparativo.linhas || []).map((linha) => `
            <tr>
                <td>${fmt(linha.campo)}</td>
                <td>${fmt(linha.email)}</td>
                <td>${fmt(linha.pdf)}</td>
                <td><span class="badge ${badgeClass(linha.status)}">${fmt(linha.status)}</span></td>
            </tr>
        `).join("");
        const loja = item.nome_loja ? `${item.nome_loja} - ${item.uf_loja}` : "CNPJ NAO CADASTRADO";
        const status = item.comparativo_status || item.status || "REVISAR";
        return `
            <article class="processing-card status-${badgeClass(status)}">
                <div class="processing-top">
                    <div>
                        <h3>${loja}</h3>
                        <p>${fmt(item.operadora)} · CNPJ ${fmt(item.cnpj)} · Valor ${fmt(item.valor)}</p>
                    </div>
                    <span class="badge ${badgeClass(status)}">${status}</span>
                </div>
                <table class="compare-table">
                    <thead><tr><th>Campo</th><th>E-mail</th><th>PDF</th><th>Status</th></tr></thead>
                    <tbody>${linhas}</tbody>
                </table>
                <div class="email-meta">
                    <span>E-mail: ${fmt(item.email_assunto)}</span>
                    <span>Recebido: ${fmt(item.email_data)}</span>
                    ${item.nome_arquivo_sugerido ? `<span>Nome sugerido: ${item.nome_arquivo_sugerido}</span>` : ""}
                </div>
            </article>
        `;
    }).join("");
}
