import pandas as pd

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 80)

CORTE = pd.Timestamp("2026-06-17")  # fin del rango documentado del dataset

def titulo(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")

def _s(x):
    """Serie a texto con NULL explicito (para que los nulos aparezcan en crosstab)."""
    return x.astype("string").fillna("NULL")

def ct(a, b, norm=False):
    print(pd.crosstab(_s(a), _s(b), normalize=norm).round(3))
    print()

def sin_acentos(s):
    return (s.astype("string").str.normalize("NFKD")
            .str.encode("ascii", "ignore").str.decode("ascii").str.lower())

def huerfanos(hijo, col, padre, colp, etiqueta):
    vals = hijo[col].dropna()
    ok = vals.isin(set(padre[colp].dropna()))
    print(f"{etiqueta:52s} filas sin padre: {(~ok).mean():7.2%} | "
          f"valores distintos sin padre: {vals[~ok].nunique():>9,} de {vals.nunique():,}")

def fase2(cust, prod, br, comp, tr, tx, ci):
    # --- fechas a datetime (en sitio) ---
    cols_fecha = [
        (cust, ["registration_date", "last_updated", "date_of_birth"]),
        (prod, ["opening_date", "expiration_date", "last_updated"]),
        (tx, ["transaction_date", "process_date"]),
        (ci, ["interaction_date", "process_date"]),
        (tr, ["process_date"]),
        (comp, ["creation_date", "process_date", "assignment_date",
                "first_response_date", "resolution_date", "closing_date"]),
    ]
    for d, cs in cols_fecha:
        for c in cs:
            d[c] = pd.to_datetime(d[c], errors="coerce")

    pais_cli = cust.drop_duplicates("customer_id").set_index("customer_id")["country"]
    dueno = prod.drop_duplicates("product_id").set_index("product_id")["customer_id"]

    # ------------------------------------------------------------------
    titulo("1. INTEGRIDAD REFERENCIAL: que hijos no tienen padre")
    huerfanos(cust, "registration_branch_id", br, "branch_id", "customers.registration_branch_id -> branches")
    huerfanos(prod, "customer_id", cust, "customer_id", "products.customer_id -> customers")
    huerfanos(prod, "opening_branch_id", br, "branch_id", "products.opening_branch_id -> branches")
    huerfanos(tx, "customer_id", cust, "customer_id", "transactions.customer_id -> customers")
    huerfanos(tx, "product_id", prod, "product_id", "transactions.product_id -> products")
    huerfanos(tx, "branch_id", br, "branch_id", "transactions.branch_id -> branches")
    huerfanos(ci, "customer_id", cust, "customer_id", "interactions.customer_id -> customers")
    huerfanos(tr, "interaction_id", ci, "interaction_id", "transcripts.interaction_id -> interactions")
    huerfanos(tr, "customer_id", cust, "customer_id", "transcripts.customer_id -> customers")
    huerfanos(comp, "customer_id", cust, "customer_id", "complaints.customer_id -> customers")
    huerfanos(comp, "affected_product_id", prod, "product_id", "complaints.affected_product_id -> products")
    huerfanos(comp, "related_branch_id", br, "branch_id", "complaints.related_branch_id -> branches")

    d = tx["product_id"].map(dueno)
    m = d.notna()
    print(f"\ntransactions cuyo customer_id != dueno del producto: {(d[m] != tx.loc[m, 'customer_id']).mean():.2%}")
    d = comp["affected_product_id"].map(dueno)
    m = d.notna()
    print(f"complaints cuyo customer_id != dueno del producto:    {(d[m] != comp.loc[m, 'customer_id']).mean():.2%}")
    print(f"clientes sin ningun producto: {(~cust['customer_id'].isin(set(prod['customer_id']))).mean():.2%}")

    # ------------------------------------------------------------------
    titulo("2. DUPLICADOS POR LLAVE DE NEGOCIO (los IDs ya son unicos)")
    print("customers.document_number repetido:", cust.duplicated("document_number").sum())
    rep = prod[prod.duplicated("product_number", keep=False)].sort_values("product_number")
    print("products.product_number repetido (filas):", len(rep))
    print(rep[["product_id", "customer_id", "product_type", "product_number", "opening_date"]].head(12))
    print("transactions mismos (cliente, producto, fecha, monto):",
          tx.duplicated(["customer_id", "product_id", "transaction_date", "amount"], keep=False).sum())
    print("interactions mismos (cliente, fecha, agente):",
          ci.duplicated(["customer_id", "interaction_date", "agent_id"], keep=False).sum())
    print("complaints mismos (cliente, fecha, categoria):",
          comp.duplicated(["customer_id", "creation_date", "category"], keep=False).sum())

    # ------------------------------------------------------------------
    titulo("3. CLIENTES / PRODUCTOS: moneda, estado, acento")
    print("Estado del producto vs. si tiene transacciones (hipotesis: solo 'Active' tiene):")
    ct(prod["product_status"], prod["product_id"].isin(set(tx["product_id"])).rename("tiene_tx"))
    print("Pais del cliente vs. moneda del producto (hipotesis: MXN aparece como USD):")
    ct(prod["customer_id"].map(pais_cli).rename("pais_cliente"), prod["currency"])
    print("Pais del cliente vs. moneda de la transaccion:")
    ct(tx["customer_id"].map(pais_cli).rename("pais_cliente"), tx["currency"])
    print("Tipo de producto vs. credit_limit nulo:")
    ct(prod["product_type"], prod["credit_limit"].isna().rename("credit_limit_nulo"))
    print("Pais vs. acento detectado en customers:")
    ct(cust["country"], cust["detected_accent"], norm="index")
    print("Tipo de documento vs. pais:")
    ct(cust["document_type"], cust["country"])
    print("Tipo de documento vs. occupation nula (coincidencia 15,039):")
    ct(cust["document_type"], cust["occupation"].isna().rename("occupation_nula"))

    # ------------------------------------------------------------------
    titulo("4. TRANSACTIONS: coherencia interna y senal de fraude")
    print("Tipo vs. canal:")
    ct(tx["transaction_type"], tx["channel"])
    print("Estado vs. response_code:")
    ct(tx["transaction_status"], tx["response_code"])
    both = tx["transaction_category"].notna() & tx["merchant_category"].notna()
    print(f"transaction_category == merchant_category (donde ambas existen): "
          f"{(tx.loc[both, 'transaction_category'] == tx.loc[both, 'merchant_category']).mean():.2%}")
    print("Categorias por comercio (max, deberia ser 1):",
          tx.dropna(subset=["merchant_name"]).groupby("merchant_name")["merchant_category"].nunique().max())
    print("\nTasa implicita amount/amount_usd por moneda (comparar luego con daily_exchange_rates):")
    print((tx["amount"] / tx["amount_usd"]).groupby(tx["currency"]).describe())

    print("\nfraud_score segun is_fraud:")
    print(tx.groupby("is_fraud")["fraud_score"].describe())
    print("\nis_fraud vs estado:")
    ct(tx["is_fraud"], tx["transaction_status"])
    print("is_fraud por pais de la transaccion (valores crudos, sin normalizar):")
    print(tx.groupby("transaction_country")["is_fraud"].agg(["sum", "mean", "size"]))
    cli = sin_acentos(tx["customer_id"].map(pais_cli))
    foraneo = (sin_acentos(tx["transaction_country"]) != cli).rename("pais_tx_distinto_al_cliente")
    print("\nTransaccion en pais distinto al del cliente -> tasa de fraude:")
    print(tx.groupby(foraneo)["is_fraud"].agg(["sum", "mean", "size"]))
    print("Valor crudo de transaction_country entre las 'foraneas':")
    print(tx.loc[foraneo, "transaction_country"].value_counts())

    cli_fraude = set(tx.loc[tx["is_fraud"], "customer_id"])
    cli_cnr = set(comp.loc[comp["category"] == "Transactions", "customer_id"])
    print(f"\nclientes con is_fraud: {len(cli_fraude):,} | con queja 'Transactions': {len(cli_cnr):,} "
          f"| interseccion: {len(cli_fraude & cli_cnr):,}")

    # ------------------------------------------------------------------
    titulo("5. COHERENCIA TEMPORAL")
    reg = cust.drop_duplicates("customer_id").set_index("customer_id")["registration_date"]
    ape = prod.drop_duplicates("product_id").set_index("product_id")["opening_date"]
    print(f"tx anteriores al registro del cliente:      {(tx['transaction_date'] < tx['customer_id'].map(reg)).mean():.2%}")
    print(f"tx anteriores al apertura del producto:   {(tx['transaction_date'] < tx['product_id'].map(ape)).mean():.2%}")
    edad = (cust["registration_date"] - cust["date_of_birth"]).dt.days / 365.25
    print(f"clientes < 18 anos al registrarse:          {(edad < 18).mean():.2%}")
    print(f"customers.last_updated < registration_date: {(cust['last_updated'] < cust['registration_date']).mean():.2%}")
    print(f"customers.last_updated > {CORTE.date()}:       {(cust['last_updated'] > CORTE).mean():.2%}")
    print(f"products.last_updated  > {CORTE.date()}:       {(prod['last_updated'] > CORTE).mean():.2%}")
    print(f"products.expiration < opening:              {(prod['expiration_date'] < prod['opening_date']).mean():.2%}")
    print(f"products 'Active' ya vencidos al corte:     "
          f"{((prod['product_status'] == 'Active') & (prod['expiration_date'] < CORTE)).mean():.2%}")
    for nombre, df_, ts in [("transactions", tx, "transaction_date"),
                           ("interactions", ci, "interaction_date"),
                           ("complaints", comp, "creation_date")]:
        print(f"{nombre}: fecha del timestamp != process_date: {(df_[ts].dt.normalize() != df_['process_date']).mean():.2%}"
              f" | hora minima {df_[ts].dt.hour.min()}h")
    orden = ["creation_date", "assignment_date", "first_response_date", "resolution_date", "closing_date"]
    print("\nOrden de fechas en complaints (debe ser creacion <= asignacion <= 1a respuesta <= resolucion <= cierre):")
    for a, b in zip(orden[:-1], orden[1:]):
        mk = comp[a].notna() & comp[b].notna()
        print(f"  {a} > {b}: {(comp.loc[mk, a] > comp.loc[mk, b]).mean():.2%}")

    # ------------------------------------------------------------------
    titulo("6. TRANSCRIPTS <-> INTERACCIONES")
    con_tr = set(ci.loc[ci["has_transcript"], "interaction_id"])
    en_tr = set(tr["interaction_id"])
    print(f"has_transcript=True sin transcript: {len(con_tr - en_tr):,} | "
          f"transcript con has_transcript=False: {len(en_tr - con_tr):,}")
    mg = tr.merge(ci[["interaction_id", "customer_id", "agent_id", "duration_seconds", "reason_category"]],
                  on="interaction_id", suffixes=("", "_ci"))
    print(f"customer_id distinto: {(mg['customer_id'] != mg['customer_id_ci']).mean():.2%} | "
          f"agent_id distinto: {(mg['agent_id'] != mg['agent_id_ci']).mean():.2%}")
    ambas = mg["duration_seconds"].notna() & mg["duration_seconds_ci"].notna()
    print(f"duracion distinta (donde ambas existen): "
          f"{(mg.loc[ambas, 'duration_seconds'] != mg.loc[ambas, 'duration_seconds_ci']).mean():.2%}")
    print(f"duracion nula en transcript pero disponible en interactions: "
          f"{(mg['duration_seconds'].isna() & mg['duration_seconds_ci'].notna()).mean():.2%}")
    print("\nmain_topics (transcript) vs reason_category (interaccion):")
    ct(mg["main_topics"], mg["reason_category"])
    print(f"full_text con placeholders '{{...}}': {tr['full_text'].str.contains(r'[{]', regex=True).mean():.2%}")
    patron = "reconoc|reconozc|desconoc|fraude|cargo|clon|robo"
    print(f"textos de cliente que mencionan fraude/desconocimiento: "
          f"{tr['customer_text'].fillna('').str.contains(patron, case=False, regex=True).sum():,}")

    # ------------------------------------------------------------------
    titulo("7. INTERACCIONES: las banderas de decision tienen senal?")
    for col in ["reason_category", "detected_sentiment", "was_resolved", "requires_followup", "channel"]:
        print(f"\nP(was_escalated=True | {col})")
        print(ci.groupby(col)["was_escalated"].mean().round(3).to_string())
    print("\nsentiment_score por detected_sentiment:")
    print(ci.groupby("detected_sentiment")["sentiment_score"].agg(["min", "mean", "max"]))
    print(f"\nnulos de acento (cliente vs agente) alineados: "
          f"{(ci['customer_detected_accent'].isna() == ci['agent_used_accent'].isna()).mean():.2%}")
    print("Acento del cliente vs acento del agente:")
    ct(ci["customer_detected_accent"], ci["agent_used_accent"])
    acc_cli = cust.set_index("customer_id")["detected_accent"]
    print("Acento en customers vs acento en interactions (mismo cliente):")
    ct(ci["customer_id"].map(acc_cli).rename("acento_customers"), ci["customer_detected_accent"])

    # ------------------------------------------------------------------
    titulo("8. QUEJAS (ground truth)")
    print("category vs subcategory (hipotesis: subcategory es funcion de category):")
    ct(comp["category"], comp["subcategory"])
    print("status vs sla_breached:")
    ct(comp["status"], comp["sla_breached"])
    print("resolution_days por prioridad y por sla_breached:")
    print(comp.groupby("priority")["resolution_days"].mean().round(1).to_string())
    print(comp.groupby("sla_breached")["resolution_days"].describe())
    dias = (comp["resolution_date"] - comp["creation_date"]).dt.days
    ok = dias.notna() & comp["resolution_days"].notna()
    print("\n|dias reales - resolution_days|:")
    print((dias[ok] - comp.loc[ok, "resolution_days"]).abs().describe())
    print("\nResueltas/Cerradas sin resolution_date:",
          ((comp["status"].isin(["Resolved", "Closed"])) & comp["resolution_date"].isna()).sum())
    abiertas = comp["status"].isin(["Open", "In Process", "Escalated"])
    print("Antiguedad (dias) de quejas sin resolver al corte:")
    print((CORTE - comp.loc[abiertas, "creation_date"]).dt.days.describe())
    mon_prod = comp["affected_product_id"].map(prod.drop_duplicates("product_id").set_index("product_id")["currency"])
    print("Moneda del producto afectado vs moneda de la queja:")
    ct(mon_prod.rename("moneda_producto"), comp["currency"])

    # ------------------------------------------------------------------
    titulo("9. GEOGRAFIA: coordenadas y telefonos")
    cero = ((br["latitude"].abs() < 1) & (br["longitude"].abs() < 1)).rename("coord_cerca_de_0_0")
    print("Sucursales con coordenadas ~(0,0) por pais:")
    ct(br["country"], cero)
    print(br.groupby("country")[["latitude", "longitude"]].agg(["min", "median", "max"]))
    pref = br["phone"].str.extract(r"^\+(\d+)")[0].rename("prefijo_tel")
    print("Pais de la sucursal vs prefijo telefonico:")
    ct(br["country"], pref)
    con = tx.dropna(subset=["latitude", "longitude"])
    print("Coordenadas de transactions por pais de la transaccion:")
    print(con.groupby("transaction_country")[["latitude", "longitude"]].agg(["min", "median", "max"]))

    # ------------------------------------------------------------------
    titulo("10. COBERTURA MENSUAL (huecos / llegadas tardias)")
    mens = pd.concat({n: g.groupby(g["process_date"].dt.to_period("M")).size()
                      for n, g in [("transactions", tx), ("interactions", ci),
                                   ("complaints", comp), ("transcripts", tr)]}, axis=1)
    print(mens.to_string())
    print("\nFilas totales vs documentado:")
    for n, g, esp in [("transactions", tx, 5_000_000), ("interactions", ci, 800_000),
                      ("complaints", comp, 80_000), ("transcripts", tr, 200_000)]:
        print(f"  {n:13s} {len(g):>10,} / {esp:>10,} = {len(g) / esp:.1%}")

def investigar_anomalias_fase3(cust, prod, comp, tx):
    print(f"\n{'=' * 78}")
    print("1. ANÁLISIS DE DESFASE TEMPORAL EN TRANSACCIONES")
    print(f"{'=' * 78}")
    
    # Extraer fechas maestras
    reg = cust.drop_duplicates("customer_id").set_index("customer_id")["registration_date"]
    ape = prod.drop_duplicates("product_id").set_index("product_id")["opening_date"]
    
    # Calcular diferencias en días (Transacción - Registro/Apertura)
    diff_reg = (tx['transaction_date'] - tx['customer_id'].map(reg)).dt.days
    diff_ape = (tx['transaction_date'] - tx['product_id'].map(ape)).dt.days
    
    # Filtrar solo los casos anómalos (valores negativos = la transacción ocurrió antes)
    anomalos_reg = diff_reg[diff_reg < 0]
    anomalos_ape = diff_ape[diff_ape < 0]
    
    print("Distribución del desfase (en DÍAS) vs Fecha de Registro del Cliente:")
    print(anomalos_reg.describe().round(1))
    
    print("\nDistribución del desfase (en DÍAS) vs Fecha de Apertura del Producto:")
    print(anomalos_ape.describe().round(1))

    
    print(f"\n{'=' * 78}")
    print("2. ANÁLISIS DE INCONSISTENCIA EN QUEJAS (CUSTOMER_ID vs PRODUCT_ID)")
    print(f"{'=' * 78}")
    
    # Mapear el dueño real del producto según la dimensión Products
    dueno_real = prod.drop_duplicates("product_id").set_index("product_id")["customer_id"]
    
    # Preparar df de análisis para quejas
    df_comp_analisis = comp[['complaint_id', 'customer_id', 'affected_product_id', 'category']].copy()
    df_comp_analisis['dueno_real_producto'] = df_comp_analisis['affected_product_id'].map(dueno_real)
    
    # Filtrar solo quejas que tienen un producto asociado
    con_producto = df_comp_analisis.dropna(subset=['affected_product_id'])
    
    print("Muestra de la discrepancia (El cliente que reclama NUNCA es el dueño):")
    print(con_producto[['complaint_id', 'customer_id', 'dueno_real_producto', 'affected_product_id']].head(5).to_string())
    
    # Validaciones semánticas
    reclamantes_existen = con_producto['customer_id'].isin(cust['customer_id']).mean()
    print(f"\n¿Los customer_id que reclaman existen en la tabla Customers?: {reclamantes_existen:.0%}")
    
    reclamantes_tienen_productos = con_producto['customer_id'].isin(prod['customer_id']).mean()
    print(f"¿Estos clientes reclamantes tienen OTROS productos a su nombre?: {reclamantes_tienen_productos:.0%}")

    
    print(f"\n{'=' * 78}")
    print("3. ANÁLISIS DEL FRAUD_SCORE Y UMBRALES DE DECISIÓN")
    print(f"{'=' * 78}")
    
    # Buscar límites entre el fraude y lo normal
    max_score_no_fraude = tx.loc[~tx['is_fraud'], 'fraud_score'].max()
    min_score_fraude = tx.loc[tx['is_fraud'], 'fraud_score'].min()
    
    print(f"Fraud Score MÁXIMO para transacciones NORMALES: {max_score_no_fraude}")
    print(f"Fraud Score MÍNIMO para transacciones con FRAUDE: {min_score_fraude}")
    
    if min_score_fraude > max_score_no_fraude:
        print(f"\n>>> HALLAZGO: Existe un umbral determinista perfecto. Todo score > {max_score_no_fraude} es Fraude Seguro.")
    else:
        print("\n>>> HALLAZGO: Los scores se solapan. El fraude no es un simple threshold inyectado.")
        
    print("\nPercentiles de fraud_score para transacciones NORMALES (is_fraud=False):")
    print(tx.loc[~tx['is_fraud'], 'fraud_score'].quantile([0.5, 0.75, 0.9, 0.95, 0.99, 1.0]).to_string())
    
    print("\nPercentiles de fraud_score para transacciones FRAUDULENTAS (is_fraud=True):")
    print(tx.loc[tx['is_fraud'], 'fraud_score'].quantile([0.0, 0.01, 0.05, 0.1, 0.25, 0.5]).to_string())