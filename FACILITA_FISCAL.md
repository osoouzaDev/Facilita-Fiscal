# Facilita Fiscal

O executável reúne três serviços na mesma janela:

## Situação Fiscal

Lê o nome da empresa ou pessoa que aparece no cabeçalho do relatório de
situação fiscal e utiliza esse nome no PDF. Não precisa de internet.

## Certidões Estaduais

Localiza o CNPJ em diferentes modelos de certidão, consulta a razão social e
utiliza esse nome no PDF. A primeira consulta de cada CNPJ precisa de internet;
as consultas seguintes aproveitam o cache local.

## Parcelamentos (DARF/DAS)

Diferencia automaticamente o Documento de Arrecadação de Receitas Federais
(DARF) e o Documento de Arrecadação do Simples Nacional (DAS). O novo nome
inclui razão social, tipo, número da parcela e vencimento. Não precisa de
internet.

## Formas de entrada

As três telas aceitam:

- Um arquivo ZIP contendo PDFs.
- Uma pasta contendo PDFs.

Ao usar ZIP, o programa cria um novo arquivo compactado e preserva o original.
Ao usar pasta, mostra uma prévia e só renomeia os arquivos após confirmação.
Arquivos repetidos recebem `(2)`, `(3)` e assim por diante.

## Uso

1. Abra `FacilitaFiscal.exe`.
2. Escolha a aba `Situação Fiscal`, `Certidões Estaduais` ou
   `Parcelamentos (DARF/DAS)`.
3. Clique em `Escolher ZIP` ou `Escolher pasta`.
4. Confira a prévia.
5. Clique em `Gerar novo ZIP` ou `Renomear arquivos`.
