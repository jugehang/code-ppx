library(nonmem2R)
library(tidyverse)
library(flextable)
library(officer)
library(stringr)
library(here)

#-------------------------------------------------------
# Step 0. Manual adjustment area (all paths and configurations at the very beginning)
#-------------------------------------------------------
args <- commandArgs(trailingOnly = TRUE)
mod_index <- if (length(args) > 0) args[1] else "41"

# 1. Model input path (reading run005_1)
model_dir <- here()
ext_file   <- paste0("run", mod_index, ".ext")
mod_file   <- paste0("run", mod_index, ".mod")
lst_file   <- paste0("run", mod_index, ".lst")

# 2. Table output path → save under tables/Basic models/
out_docx    <- paste0("Table5_Run", mod_index, "_Final_Parameters.docx")

# 3. Table caption
table_caption <- paste0("Table 5. Final model parameters (Run ", mod_index, ")")

#-------------------------------------------------------
# Load model results
#-------------------------------------------------------
ext <- extload(ext_file)

#-------------------------------------------------------
# Unified format, set decimal places (2 digits after decimal point)
#-------------------------------------------------------
fmt_tbl <- function(df){
  df %>%
    mutate(
      Estimate = ifelse(is.na(Estimate) | Estimate=="-", "-", sprintf("%.2f", as.numeric(Estimate))),
      SE       = ifelse(is.na(SE) | SE=="-", "-", sprintf("%.2f", as.numeric(SE))),
      RSE      = ifelse(is.na(RSE) | RSE=="-", "-", sprintf("%.2f", as.numeric(RSE)))) %>%
    mutate(across(c(Estimate, SE, RSE), as.character))}

#-------------------------------------------------------
# Step 1: Extract parameter labels from .mod file
#-------------------------------------------------------
extract_param_map_from_mod <- function(mod_file){
  mod <- readLines(mod_file, warn = FALSE)
  mod <- mod[trimws(mod) != ""]

  get_comment <- function(x){
    if(str_detect(x, ";")){
      comment_part <- str_trim(str_extract(x, "(?<=;).*$"))
      if(str_detect(comment_part, "\\[")){
        label <- str_extract(comment_part, "(?<=\\[)[^\\]]+")
        return(label)
      } else {
        return(comment_part)}}
    return(NA_character_)}

  parse_block <- function(keyword, prefix){
    idx_start <- which(str_detect(str_to_upper(trimws(mod)), paste0("^\\$", keyword)))
    if(length(idx_start) == 0) return(tibble())

    idx_start <- idx_start[1]
    idx_end <- min(which(str_detect(trimws(mod), "^\\$") & seq_along(mod) > idx_start), na.rm = TRUE)
    if(is.infinite(idx_end)) idx_end <- length(mod) + 1

    block_lines <- mod[idx_start:(idx_end-1)]
    block_lines[1] <- str_replace(block_lines[1], paste0("^\\$", keyword), "")
    block_lines <- str_trim(block_lines)
    block_lines <- block_lines[block_lines != ""]

    tibble(
      Type = keyword,
      Parameter = paste0(prefix, seq_along(block_lines)),
      Label = sapply(block_lines, get_comment),
      RawLine = block_lines
    ) %>%
      mutate(Label = ifelse(is.na(Label) | Label=="", Parameter, Label))}

  theta_map <- parse_block("THETA", "THETA") %>% mutate(Type="THETA")
  omega_map <- parse_block("OMEGA", "OMEGA") %>% mutate(Type="OMEGA")
  sigma_map <- parse_block("SIGMA", "SIGMA") %>% mutate(Type="SIGMA")

  bind_rows(theta_map, omega_map, sigma_map) %>%
    select(Type, Parameter, Label)
}

#-------------------------------------------------------
# Step 2: Generate parameter table
#-------------------------------------------------------
make_param_table_from_ext_mod <- function(ext, mod_file){

  map <- extract_param_map_from_mod(mod_file)

  theta_tbl <- tibble(
    Type = "THETA",
    Parameter = names(ext$theta),
    Estimate  = as.numeric(ext$theta),
    SE        = as.numeric(ext$theta.sd)) %>%
    mutate(
      RSE = ifelse(SE > 1e9 | is.na(SE), NA, SE/Estimate*100),
      RSE = ifelse(is.na(RSE), "-", sprintf("%.1f", RSE)),
      Estimate = signif(Estimate, 4),
      SE = ifelse(SE > 1e9 | is.na(SE), "-", signif(SE, 3))) %>%
    left_join(map %>% filter(Type=="THETA"), by = c("Type","Parameter")) %>%
    mutate(Label = ifelse(is.na(Label), Parameter, Label))

  omega_var    <- diag(ext$omega)
  omega_var_se <- diag(ext$omega.sd)

  bsv     <- 100 * sqrt(omega_var)
  bsv_se  <- (100 / (2 * sqrt(omega_var))) * omega_var_se
  bsv_rse <- bsv_se / bsv * 100

  omega_tbl <- tibble(
    Type = "BSV(%)",
    Parameter = names(omega_var),
    Estimate  = as.numeric(bsv),
    SE        = as.numeric(bsv_se),
    RSE       = as.numeric(bsv_rse)) %>%
    mutate(
      SE  = ifelse(SE > 1e9 | is.na(SE), NA, SE),
      RSE = ifelse(SE > 1e9 | is.na(SE), NA, RSE),
      Estimate = ifelse(is.nan(Estimate) | is.infinite(Estimate), NA, Estimate),
      Estimate = ifelse(is.na(Estimate), "-", signif(Estimate, 4)),
      SE       = ifelse(is.na(SE), "-", signif(SE, 3)),
      RSE      = ifelse(is.na(RSE), "-", sprintf("%.1f", RSE))
    ) %>%
    left_join(map %>% filter(Type=="OMEGA") %>% select(Parameter, Label), by = "Parameter") %>%
    mutate(Label = ifelse(is.na(Label), Parameter, Label)) %>%
    select(Type, Label, Estimate, SE, RSE)

  if(length(ext$sigma) > 0 && !all(diag(ext$sigma) == 1)) {
    sigma_var <- diag(ext$sigma)
    sigma_se  <- diag(ext$sigma.sd)

    sigma_tbl <- tibble(
      Type = "SIGMA",
      Parameter = names(sigma_var),
      Estimate  = as.numeric(sigma_var),
      SE        = as.numeric(sigma_se)) %>%
      mutate(
        RSE = ifelse(SE > 1e9 | is.na(SE), NA, SE/Estimate*100),
        RSE = ifelse(is.na(RSE), "-", sprintf("%.1f", RSE)),
        Estimate = signif(Estimate, 4),
        SE = ifelse(SE > 1e9 | is.na(SE), "-", signif(SE, 3))
      ) %>%
      left_join(map %>% filter(Type=="SIGMA"), by = c("Type","Parameter")) %>%
      mutate(
        Label = ifelse(is.na(Label) | Label == "", Parameter, Label),
        Label = ifelse(!str_detect(Label, "error$"), paste0(Label, " error"), Label))
  } else {
    sigma_tbl <- tibble(
      Type = character(), Label = character(), Estimate = character(), SE = character(), RSE = character())}

  theta_fixed_tbl <- theta_tbl %>%
    mutate(
      NewType = case_when(
        str_detect(Label, "Proportional|Additive|error") ~ "Residual Error",
        str_detect(Label, "CL|V|KA|Tlag|F|Ka") ~ "PK Parameter",
        TRUE ~ "THETA")) %>%
    select(Type = NewType, Label, Estimate, SE, RSE)

  final_tbl <- bind_rows(
    fmt_tbl(theta_fixed_tbl),
    fmt_tbl(omega_tbl),
    fmt_tbl(sigma_tbl))

  return(final_tbl)}

#-------------------------------------------------------
# Extract model fit metrics
#-------------------------------------------------------
extract_model_fit_metrics <- function(ext, mod_file = NULL) {
  ofv <- ext$ofv
  mod_lines <- readLines(mod_file, warn = FALSE)

  theta_fix_count <- 0
  theta_section <- FALSE
  for(line in mod_lines) {
    if(grepl("^\\$THETA", toupper(trimws(line)))) { theta_section <- TRUE; next}
    if(theta_section && grepl("^\\$", line)) theta_section <- FALSE
    if(theta_section && grepl("FIX", toupper(line))) theta_fix_count <- theta_fix_count + 1}
  n_theta_est <- length(ext$theta) - theta_fix_count

  omega_fix_count <- 0
  omega_section <- FALSE
  for(line in mod_lines) {
    if(grepl("^\\$OMEGA", toupper(trimws(line)))) { omega_section <- TRUE; next}
    if(omega_section && grepl("^\\$", line)) omega_section <- FALSE
    if(omega_section && grepl("FIX", toupper(line))) omega_fix_count <- omega_fix_count + 1}
  n_omega_est <- length(diag(ext$omega)) - omega_fix_count

  sigma_fix_count <- 0
  sigma_section <- FALSE
  for(line in mod_lines) {
    if(grepl("^\\$SIGMA", toupper(trimws(line)))) { sigma_section <- TRUE; next}
    if(sigma_section && grepl("^\\$", line)) sigma_section <- FALSE
    if(sigma_section && grepl("FIX", toupper(line))) sigma_fix_count <- sigma_fix_count + 1}
  n_sigma_est <- length(diag(ext$sigma)) - sigma_fix_count

  n_params <- n_theta_est + n_omega_est + n_sigma_est
  aic <- ofv + 2 * n_params

  tibble(
    Label = c("OFV", "AIC"),
    Estimate = c(sprintf("%.2f", ofv), sprintf("%.2f", aic)),
    SE = c("-", "-"),
    RSE = c("-", "-"))}

#-------------------------------------------------------
# Step 3: Generate three-line table + export to Word (using paths defined at the beginning)
#-------------------------------------------------------
# Font configuration
base_font        <- "Times New Roman"
body_fontsize    <- 10
header_fontsize  <- 10
title_fontsize   <- 14

# Data processing
fit_metrics <- extract_model_fit_metrics(ext, mod_file)

param_tbl <- make_param_table_from_ext_mod(ext, mod_file) %>%
  mutate(Type = factor(Type, levels = c("PK Parameter", "BSV(%)", "Residual Error", "SIGMA"))) %>%
  arrange(Type) %>%
  select(-Type)

param_tbl_with_metrics <- bind_rows(fit_metrics, param_tbl)

ft <- flextable(param_tbl_with_metrics)

ft <- set_header_labels(
  ft,
  Label = "Parameter",
  Estimate = "Estimate",
  SE = "SE",
  RSE = "RSE (%)")

ft <- theme_booktabs(ft)
ft <- font(ft, fontname = base_font, part = "all")
ft <- fontsize(ft, size = body_fontsize, part = "body")
ft <- fontsize(ft, size = header_fontsize, part = "header")
ft <- bold(ft, part = "header", bold = TRUE)

# Column width settings
ft <- width(ft, j = 1, width = 4.5 / 2.54)
ft <- width(ft, j = 2:4, width = 3.5 / 2.54)

# Alignment (fix: use column index 1 for 100% robustness)
ft <- align(ft, align = "center", part = "all")
ft <- align(ft, j = 1, align = "left", part = "all")  # First column (Parameter) left-aligned

# Vertical centering
ft <- valign(ft, j = seq_len(ncol(param_tbl_with_metrics)), valign = "center", part = "all")

# Cell padding
ft <- padding(
  ft,
  padding.top = 1,
  padding.bottom = 1,
  padding.left = 2,
  padding.right = 2,
  part = "all")

# Auto-fit
ft <- autofit(ft)
ft <- set_table_properties(ft, layout = "autofit", width = 1)

# Title
title_fp <- fp_text(
  font.size   = title_fontsize,
  bold        = TRUE,
  italic      = FALSE,
  font.family = base_font)

title_par <- fpar(
  ftext(table_caption, prop = title_fp),
  fp_p = fp_par(text.align = "center"))

# Export
doc <- read_docx()
doc <- body_add_fpar(doc, value = title_par)
doc <- body_add_flextable(doc, value = ft)

print(doc, target = out_docx)
# --- 新增：吐出 CSV 供 Python 进行 AI 核对 ---
write.csv(param_tbl_with_metrics, paste0("data_run", mod_index, ".csv"), row.names = FALSE)
message(">>> CSV Data exported for Run ", mod_index)
