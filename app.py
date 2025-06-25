import streamlit as st
import os
import re
import tempfile
import zipfile
from io import BytesIO


def modificar_estrategia_escalado_gerard(content, filename):
    """
    Modifica contenido de estrategia MQL5 para añadir gestión de riesgo por niveles
    """
    # Evita modificar un archivo que ya ha sido procesado
    if "Risk Management (Precise Level Scaling)" in content:
        return (
            None,
            f"El archivo '{filename}' ya parece tener la gestión de riesgo precisa.",
        )

    # Correcciones de warnings comunes
    content = content.replace(
        'return("File not found in the MQL5\\Files directory to send on FTP server");',
        'return("File not found in the MQL5\\\\Files directory to send on FTP server");',
    )
    content = content.replace("0.5f", "0.5")
    content = content.replace("10.0f", "10.0")

    # Bloques de código MQL5
    risk_management_inputs = """
    //+------------------------------------------------------------------+
    //| Risk Management (Precise Level Scaling) by Python Script
    //+------------------------------------------------------------------+
    input string g_riskScalingTitle = "----------- Risk Management (Level Scaling) -----------";
    input string g_riskLevels_string = "1.0,1.2,1.6,2.4,3.6,4.5"; // Risk % por nivel, separado por comas

    // --- Internal State Variables ---
    double g_riskLevels[];          // Array para guardar los niveles de riesgo parseados
    int    g_currentTradeLevel;     // Nivel actual del Trade (1-based, ej: 1, 2, 3...)
    string g_gv_tradeLevel_key;     // Clave para la Variable Global

    """

    on_init_addition = """
    // --- Inicialización de Gestión de Riesgo por Niveles ---
    g_gv_tradeLevel_key = "SQ.TradeLevel." + StrategyID;

    string risk_levels_parts[];
    StringSplit(g_riskLevels_string, ',', risk_levels_parts);
    ArrayResize(g_riskLevels, ArraySize(risk_levels_parts));
    for(int i = 0; i < ArraySize(risk_levels_parts); i++)
    {
        g_riskLevels[i] = StringToDouble(risk_levels_parts[i]);
    }

    if(ArraySize(g_riskLevels) == 0)
    {
        Alert("Error en Gestión de Riesgo: La cadena de niveles de riesgo está vacía o mal formada.");
        return(INIT_FAILED);
    }

    if(GlobalVariableCheck(g_gv_tradeLevel_key)) {
        g_currentTradeLevel = (int)GlobalVariableGet(g_gv_tradeLevel_key);
    } else {
        g_currentTradeLevel = 1; 
        GlobalVariableSet(g_gv_tradeLevel_key, g_currentTradeLevel);
    }
    
    VerboseLog("Gestión de Riesgo por Niveles Inicializada. Nivel Actual: ", IntegerToString(g_currentTradeLevel));
    // --- Fin de la Inicialización ---
    """

    on_trade_transaction_function = """
    //+------------------------------------------------------------------+
    //| Gestor de Eventos de Transacción para Gestión de Riesgo por Niveles |
    //+------------------------------------------------------------------+
    void OnTradeTransaction(const MqlTradeTransaction &trans,
                            const MqlTradeRequest &request,
                            const MqlTradeResult &result)
    {
    if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
    {
        if(HistoryDealSelect(trans.deal))
        {
            if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) == MagicNumber)
            {
                if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) == DEAL_ENTRY_OUT)
                {
                double dealProfit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
                
                if(dealProfit < 0) 
                {
                    g_currentTradeLevel++; 
                    if(g_currentTradeLevel > ArraySize(g_riskLevels))
                    {
                        g_currentTradeLevel = ArraySize(g_riskLevels);
                    }
                    VerboseLog("GESTION POR NIVELES: Trade PERDEDOR. Avanzando al Nivel ", IntegerToString(g_currentTradeLevel));
                }
                else
                {
                    g_currentTradeLevel = 1;
                    VerboseLog("GESTION POR NIVELES: Trade GANADOR. Reseteando al Nivel 1.");
                }
                GlobalVariableSet(g_gv_tradeLevel_key, g_currentTradeLevel);
                }
            }
        }
    }
    }
    """

    lot_size_calculation_logic = """
          // --- Cálculo de Gestión de Riesgo por Niveles ---
          if(g_currentTradeLevel < 1 || g_currentTradeLevel > ArraySize(g_riskLevels))
          {
             g_currentTradeLevel = 1; 
             GlobalVariableSet(g_gv_tradeLevel_key, g_currentTradeLevel);
          }
          
          double riskPercentForTrade = g_riskLevels[g_currentTradeLevel - 1];
          
          double moneyToRisk = (initialBalance * riskPercentForTrade) / 100.0;
          VerboseLog("GESTION POR NIVELES: Nivel actual: ", IntegerToString(g_currentTradeLevel), ". Arriesgando: ", DoubleToString(riskPercentForTrade, 2), "%. Dinero máximo a arriesgar: ", DoubleToString(moneyToRisk, 2));
          
          size = sqMMFixedAmount("Current",ORDER_TYPE_BUY,openPrice,sl,moneyToRisk,mmDecimals,mmLotsIfNoMM,mmMaxLots,mmMultiplier,mmStep);"""

    precise_mm_function = """
    double sqMMFixedAmount(string symbol, ENUM_ORDER_TYPE orderType, double price, double sl, double RiskedMoney, int decimals, double LotsIfNoMM, double MaximumLots, double multiplier, double sizeStep) {
    Verbose("Computing Money Management for order - Precise amount");
    
    if(UseMoneyManagement == false) {
        Verbose("Use Money Management = false, MM not used");
        return (mmLotsIfNoMM);
    }
        
    string correctedSymbol = correctSymbol(symbol);
    sl = NormalizeDouble(sl, (int) SymbolInfoInteger(correctedSymbol, SYMBOL_DIGITS));
    
    double openPrice = price > 0 ? price : SymbolInfoDouble(correctedSymbol, isLongOrder(orderType) ? SYMBOL_ASK : SYMBOL_BID);
    double LotSize=0;

    if(RiskedMoney <= 0 ) {
        Verbose("Computing Money Management - Incorrect RiskedMoney value, it must be above 0");
        return(0);
    }
    
    double PointValue = SymbolInfoDouble(correctedSymbol, SYMBOL_TRADE_TICK_VALUE) / SymbolInfoDouble(correctedSymbol, SYMBOL_TRADE_TICK_SIZE); 
    double Smallest_Lot = SymbolInfoDouble(correctedSymbol, SYMBOL_VOLUME_MIN);
    double Largest_Lot = SymbolInfoDouble(correctedSymbol, SYMBOL_VOLUME_MAX);    
    
    if (PointValue <= 0 || MathAbs(openPrice - sl) <= 0) {
        Verbose("Cannot calculate lot size: Point value or SL distance is zero. Using default lot size.");
        return LotsIfNoMM;
    }
    
    double oneLotSLDrawdown = PointValue * MathAbs(openPrice - sl);
            
    if(oneLotSLDrawdown > 0) {
        LotSize = RiskedMoney / oneLotSLDrawdown;
    }
    else {
        LotSize = 0;
    }

        LotSize = LotSize * multiplier;
        
        if(sizeStep > 0) {
            LotSize = MathFloor(LotSize / sizeStep) * sizeStep;
        }

    Verbose("Computing Money Management - Smallest_Lot: ", DoubleToString(Smallest_Lot), ", Largest_Lot: ", DoubleToString(Largest_Lot), ", Computed LotSize: ", DoubleToString(LotSize, 8));
    Verbose("Money to risk: ", DoubleToString(RiskedMoney), ", Max 1 lot trade drawdown: ", DoubleToString(oneLotSLDrawdown), ", Point value: ", DoubleToString(PointValue));

    if(LotSize <= 0) {
        Verbose("Calculated LotSize is <= 0. Using LotsIfNoMM value: ", DoubleToString(LotsIfNoMM), ")");
        LotSize = LotsIfNoMM;
        }                              

    if (LotSize < Smallest_Lot) {
        Verbose("Calculated LotSize is too small (", DoubleToString(LotSize,8), "). Minimal allowed is ", DoubleToString(Smallest_Lot), ". Trade will be skipped.");
        return 0;
    }
    else if (LotSize > Largest_Lot) {
        Verbose("LotSize is too big. LotSize set to maximal allowed market value: ", DoubleToString(Largest_Lot));
        LotSize = Largest_Lot;
    }

    if(LotSize > MaximumLots) {
        Verbose("LotSize is too big. LotSize set to maximal allowed value (MaximumLots): ", DoubleToString(MaximumLots));
        LotSize = MaximumLots;
    }

    return (LotSize);
    }"""

    # Aplicar modificaciones
    content = re.sub(
        r"double sqMMFixedAmount\(string symbol,.*?\)\s*{.*?^}",
        lambda m: precise_mm_function,
        content,
        flags=re.DOTALL | re.MULTILINE,
    )

    target_for_inputs = (
        'input string smm = "----------- Money Management - Fixed Amount -----------";'
    )
    content = content.replace(
        target_for_inputs, risk_management_inputs + "\n" + target_for_inputs
    )

    target_for_oninit = "   return(INIT_SUCCEEDED);"
    content = content.replace(
        target_for_oninit, on_init_addition + "\n\n   " + target_for_oninit
    )

    original_lot_calc_line = 'size = sqMMFixedAmount("Current",ORDER_TYPE_BUY,openPrice,sl,mmRiskedMoney,mmDecimals,mmLotsIfNoMM,mmMaxLots,mmMultiplier,mmStep);'
    match = re.search(r"(\s*)" + re.escape(original_lot_calc_line), content)
    if match:
        indentation = match.group(1)
        indented_logic = "\n".join(
            [indentation + line for line in lot_size_calculation_logic.split("\n")]
        )
        content = content.replace(indentation + original_lot_calc_line, indented_logic)

    first_include_marker = "//+----------------------------- Include from"
    if first_include_marker in content:
        content = content.replace(
            first_include_marker,
            on_trade_transaction_function + "\n\n" + first_include_marker,
            1,
        )
    else:
        content += "\n\n" + on_trade_transaction_function

    return content, "Estrategia modificada con éxito - Escalado Preciso"


def modificar_estrategia_benjamin(content, filename):
    """
    Modifica contenido de estrategia MQL5 para añadir gestión de riesgo para cuentas de fondeo
    """
    # Evita modificar un archivo que ya ha sido procesado
    if "Risk Management for Funded Accounts" in content:
        return None, f"El archivo '{filename}' ya parece estar modificado."

    # Correcciones de warnings
    content = content.replace(
        'return("File not found in the MQL5\\Files directory to send on FTP server");',
        'return("File not found in the MQL5\\\\Files directory to send on FTP server");',
    )
    content = content.replace("0.5f", "0.5")
    content = content.replace("10.0f", "10.0")

    # Bloques de código MQL5
    risk_management_inputs = """
    //+------------------------------------------------------------------+
    //| Risk Management for Funded Accounts by Python Script (V2 - Corrected)
    //+------------------------------------------------------------------+
    input string g_riskManagementTitle = "----------- Risk Management (Funded Accounts) -----------";
    input double g_initialRiskPercent = 1.0;       // Riesgo Inicial %
    input double g_riskStep = 0.25;                // Paso de Riesgo % por Ganancia/Pérdida
    input double g_maxLossThreshold = -4.0;        // Umbral de Pérdida Máxima %
    input double g_maxLossRisk = 1.0;              // Riesgo % tras alcanzar Umbral de Pérdida
    input double g_profitProtectThreshold = 4.0;   // Umbral de Protección de Ganancias %
    input double g_profitProtectRisk = 0.75;       // Riesgo % tras alcanzar Protección de Ganancias
    input double g_minRiskPercent = 0.25;          // Riesgo mínimo permitido %

    // --- Variables de estado internas (no modificar)
    double g_currentRiskPercent;
    double g_totalAccountProfitPercent;
    string g_gv_riskPercent_key;
    string g_gv_profitPercent_key;

    """

    on_init_addition = """
    // --- Inicialización de Variables de Gestión de Riesgo ---
    g_gv_riskPercent_key = "SQ.Risk." + StrategyID;
    g_gv_profitPercent_key = "SQ.Profit." + StrategyID;

    if(GlobalVariableCheck(g_gv_riskPercent_key)) {
        g_currentRiskPercent = GlobalVariableGet(g_gv_riskPercent_key);
    } else {
        g_currentRiskPercent = g_initialRiskPercent;
        GlobalVariableSet(g_gv_riskPercent_key, g_currentRiskPercent);
    }

    if(GlobalVariableCheck(g_gv_profitPercent_key)) {
        g_totalAccountProfitPercent = GlobalVariableGet(g_gv_profitPercent_key);
    } else {
        g_totalAccountProfitPercent = 0.0;
        GlobalVariableSet(g_gv_profitPercent_key, g_totalAccountProfitPercent);
    }
    
    VerboseLog("Gestión de Riesgo Inicializada. Riesgo Actual: ", DoubleToString(g_currentRiskPercent, 2), "%, P/L Total: ", DoubleToString(g_totalAccountProfitPercent, 2), "%");
    // --- Fin de la Inicialización de Gestión de Riesgo ---
    """

    on_trade_transaction_function = """
    //+------------------------------------------------------------------+
    //| Gestor de Eventos de Transacción para Gestión de Riesgo          |
    //+------------------------------------------------------------------+
    void OnTradeTransaction(const MqlTradeTransaction &trans,
                            const MqlTradeRequest &request,
                            const MqlTradeResult &result)
    {
    if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
    {
        if(HistoryDealSelect(trans.deal))
        {
            if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) == MagicNumber)
            {
                if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) == DEAL_ENTRY_OUT)
                {
                double dealProfit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
                
                if(initialBalance <= 0)
                {
                    VerboseLog("Error en Gestión de Riesgo: InitialCapital debe ser > 0 para el cálculo de porcentaje.");
                    return; 
                }

                double profitPercent = (dealProfit / initialBalance) * 100.0;
                g_totalAccountProfitPercent += profitPercent;
                
                if(dealProfit >= 0)
                {
                    g_currentRiskPercent -= g_riskStep;
                    if(g_currentRiskPercent < g_minRiskPercent) 
                    {
                        g_currentRiskPercent = g_minRiskPercent;
                    }
                }
                else
                {
                    g_currentRiskPercent += g_riskStep;
                }

                GlobalVariableSet(g_gv_riskPercent_key, g_currentRiskPercent);
                GlobalVariableSet(g_gv_profitPercent_key, g_totalAccountProfitPercent);
                
                VerboseLog("GESTION DE RIESGO: Trade Cerrado. P/L: ", DoubleToString(dealProfit, 2), " (", DoubleToString(profitPercent, 2), "%). Nuevo P/L Total: ", DoubleToString(g_totalAccountProfitPercent, 2), "%. Próximo Riesgo: ", DoubleToString(g_currentRiskPercent, 2), "%");
                }
            }
        }
    }
    }
    """

    lot_size_calculation_logic = """
    // --- Cálculo de Gestión de Riesgo Dinámico ---
    double riskPercentForTrade = g_currentRiskPercent;
    if(g_totalAccountProfitPercent <= g_maxLossThreshold) {
        riskPercentForTrade = g_maxLossRisk;
        VerboseLog("GESTION DE RIESGO: Protección de Drawdown activada. Riesgo fijado a: ", DoubleToString(riskPercentForTrade, 2), "%");
    } else if (g_totalAccountProfitPercent >= g_profitProtectThreshold) {
        riskPercentForTrade = g_profitProtectRisk;
        VerboseLog("GESTION DE RIESGO: Protección de Ganancias activada. Riesgo fijado a: ", DoubleToString(riskPercentForTrade, 2), "%");
    }
    
    double moneyToRisk = (initialBalance * riskPercentForTrade) / 100.0;
    VerboseLog("GESTION DE RIESGO: Calculando tamaño de lote. Usando riesgo de: ", DoubleToString(riskPercentForTrade, 2), "%. Dinero a arriesgar: ", DoubleToString(moneyToRisk, 2));
    
    size = sqMMFixedAmount("Current",ORDER_TYPE_BUY,openPrice,sl,moneyToRisk,mmDecimals,mmLotsIfNoMM,mmMaxLots,mmMultiplier,mmStep);"""

    # Aplicar modificaciones
    target_for_inputs = (
        'input string smm = "----------- Money Management - Fixed Amount -----------";'
    )
    content = content.replace(
        target_for_inputs, risk_management_inputs + "\n" + target_for_inputs
    )

    target_for_oninit = "   return(INIT_SUCCEEDED);"
    content = content.replace(
        target_for_oninit, on_init_addition + "\n\n   " + target_for_oninit
    )

    original_lot_calc_line = 'size = sqMMFixedAmount("Current",ORDER_TYPE_BUY,openPrice,sl,mmRiskedMoney,mmDecimals,mmLotsIfNoMM,mmMaxLots,mmMultiplier,mmStep);'
    match = re.search(r"(\s*)" + re.escape(original_lot_calc_line), content)
    if match:
        indentation = match.group(1)
        indented_lot_size_logic = "\n".join(
            [
                indentation + line if line.strip() else ""
                for line in lot_size_calculation_logic.split("\n")
            ]
        )
        content = content.replace(
            indentation + original_lot_calc_line, indented_lot_size_logic
        )

    first_include_marker = "//+----------------------------- Include from"
    if first_include_marker in content:
        content = content.replace(
            first_include_marker,
            on_trade_transaction_function + "\n\n" + first_include_marker,
            1,
        )
    else:
        content += "\n\n" + on_trade_transaction_function

    return content, "Estrategia modificada con éxito - Cuentas de Fondeo"


def main():
    st.set_page_config(
        page_title="Modificador de Estrategias MQL5", page_icon="📈", layout="wide"
    )

    st.title("📈 Modificador de Estrategias MQL5")
    st.markdown("---")

    # Información sobre las metodologías
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🎯 Escalado Gerard")
        st.markdown(
            """
        **Características:**
        - Gestión de riesgo por niveles predefinidos
        - Escalado tras pérdidas consecutivas
        - Reset a nivel 1 tras ganancia
        - Niveles configurables: 1.0%, 1.2%, 1.6%, 2.4%, 3.6%, 4.5%
        """
        )

    with col2:
        st.subheader("💰 Escalado Benjamin")
        st.markdown(
            """
        **Características:**
        - Gestión dinámica basada en P&L acumulado
        - Protección de drawdown y ganancias
        - Ajuste automático del riesgo
        - Ideal para cuentas de fondeo/prop trading
        """
        )

    st.markdown("---")

    # Selector de metodología
    metodologia = st.selectbox(
        "🔧 Selecciona la metodología de gestión de riesgo:",
        ["Escalado Metodología Gerard", "Escalado Metodología Benjamin"],
        help="Elige la metodología que mejor se adapte a tu estrategia de trading",
    )
    if metodologia == "Escalado Metodología Benjamin":
        st.info("📺 **Video explicativo de esta metodología:**")
        st.video("https://www.youtube.com/watch?v=h_RXCyKqZVU&list=WL&index=13&t=459s")
        st.caption(
            "Este video explica en detalle cómo funciona la gestión de riesgo para cuentas de fondeo"
        )

    # Carga de archivos
    st.subheader("📁 Cargar archivos .mq5")
    uploaded_files = st.file_uploader(
        "Selecciona uno o más archivos .mq5 para modificar:",
        type=["mq5"],
        accept_multiple_files=True,
        help="Puedes seleccionar múltiples archivos .mq5 para procesarlos en lote",
    )

    if uploaded_files:
        st.success(f"✅ {len(uploaded_files)} archivo(s) cargado(s)")

        # Mostrar archivos cargados
        with st.expander("Ver archivos cargados"):
            for file in uploaded_files:
                st.write(f"• {file.name} ({file.size} bytes)")

        # Botón de procesamiento
        if st.button("🚀 Procesar Archivos", type="primary"):
            # Crear archivo ZIP con los resultados
            zip_buffer = BytesIO()

            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                procesados = 0
                errores = 0

                # Crear barra de progreso
                progress_bar = st.progress(0)
                status_text = st.empty()

                for i, uploaded_file in enumerate(uploaded_files):
                    # Actualizar progreso
                    progress = (i + 1) / len(uploaded_files)
                    progress_bar.progress(progress)
                    status_text.text(f"Procesando: {uploaded_file.name}")

                    try:
                        # Leer contenido del archivo
                        content = uploaded_file.read().decode("utf-8")

                        # Aplicar la modificación según la metodología seleccionada
                        if metodologia == "Escalado Metodología Gerard":
                            modified_content, message = (
                                modificar_estrategia_escalado_gerard(
                                    content, uploaded_file.name
                                )
                            )
                            suffix = "_escalado_gerard"
                        else:
                            modified_content, message = modificar_estrategia_benjamin(
                                content, uploaded_file.name
                            )
                            suffix = "_escalado_benjamin"

                        if modified_content:
                            # Generar nombre de archivo modificado
                            base_name = os.path.splitext(uploaded_file.name)[0]
                            new_filename = f"{base_name}{suffix}.mq5"

                            # Añadir al ZIP
                            zip_file.writestr(new_filename, modified_content)
                            procesados += 1

                            st.success(f"✅ {uploaded_file.name}: {message}")
                        else:
                            errores += 1
                            st.warning(f"⚠️ {uploaded_file.name}: {message}")

                    except Exception as e:
                        errores += 1
                        st.error(f"❌ Error procesando {uploaded_file.name}: {str(e)}")

                # Completar progreso
                progress_bar.progress(1.0)
                status_text.text("¡Procesamiento completado!")

            # Mostrar resumen
            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Archivos Procesados", procesados)
            with col2:
                st.metric("Errores/Omitidos", errores)
            with col3:
                st.metric("Total", len(uploaded_files))

            # Botón de descarga
            if procesados > 0:
                zip_buffer.seek(0)
                st.download_button(
                    label="📥 Descargar Archivos Modificados",
                    data=zip_buffer.getvalue(),
                    file_name=f"estrategias_modificadas_{metodologia.lower().replace(' ', '_')}.zip",
                    mime="application/zip",
                    type="primary",
                )

                st.info(
                    "💡 **Consejo:** Los archivos modificados están listos para compilar en MetaEditor."
                )

    # Información adicional
    st.markdown("---")
    with st.expander("ℹ️ Información adicional"):
        st.markdown(
            """
        ### ¿Cómo usar esta herramienta?
        
        1. **Selecciona la metodología** que mejor se adapte a tu estilo de trading
        2. **Carga tus archivos .mq5** (puedes seleccionar múltiples archivos)
        3. **Haz clic en "Procesar Archivos"** para aplicar las modificaciones
        4. **Descarga el archivo ZIP** con los archivos modificados
        5. **Compila los archivos** en MetaEditor y úsalos en MetaTrader 5
        
        ### Características técnicas:
        - ✅ Corrección automática de warnings comunes
        - ✅ Gestión de variables globales para persistencia
        - ✅ Logging detallado para debugging
        - ✅ Validación de parámetros de entrada
        - ✅ Compatibilidad con múltiples símbolos
        
        ### Requisitos:
        - Los archivos deben tener la estructura estándar de StrategyQuant
        - Se recomienda hacer backup de los archivos originales
        """
        )


if __name__ == "__main__":
    main()
