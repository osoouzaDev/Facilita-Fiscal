# Renomeador de Relatórios Fiscais

Aplicação em Python que lê o nome da empresa ou da pessoa dentro dos relatórios
de situação fiscal da Receita Federal e renomeia cada PDF com esse nome.

No modelo analisado, a informação vem nesta linha:

```text
CNPJ: 49.084.778 - MAURICIO PLOSZAI TAPECARIA AUTOMOTIVA
```

O PDF já possui texto pesquisável. Por isso, o programa faz a leitura direta e
não converte o documento para XML nem usa OCR.

São reconhecidos os cabeçalhos de pessoa jurídica (`CNPJ: ... - NOME`) e de
pessoa física (`CPF: ... - NOME`).

## Instalação no Windows

É necessário ter o Python 3.10 ou mais recente instalado.

Abra o PowerShell nesta pasta e execute uma vez:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Isso mantém a biblioteca do programa isolada das demais instalações do Python.

## Uso com a interface gráfica

1. Dê dois cliques em `iniciar_renomeador.bat`.
2. Clique em **Escolher pasta**.
3. Confira a prévia dos nomes.
4. Clique em **Renomear arquivos** e confirme.

O programa nunca sobrescreve outro arquivo. Quando duas empresas gerarem o
mesmo nome, serão usados nomes como `EMPRESA.pdf` e `EMPRESA (2).pdf`.

Arquivos cujo cabeçalho não for reconhecido aparecem como erro e permanecem
inalterados.

## Uso pelo PowerShell

Apenas visualizar o que seria alterado:

```powershell
.\.venv\Scripts\python.exe renomeador_pdfs.py "C:\caminho\da\pasta"
```

Aplicar as alterações:

```powershell
.\.venv\Scripts\python.exe renomeador_pdfs.py "C:\caminho\da\pasta" --aplicar
```

Para também procurar dentro das subpastas, acrescente `--recursivo`.

## Segurança

- A aplicação mostra uma prévia antes de alterar os arquivos pela interface.
- PDFs não reconhecidos não são renomeados.
- Arquivos existentes não são substituídos.
- Caracteres que o Windows não permite em nomes de arquivos são removidos.
