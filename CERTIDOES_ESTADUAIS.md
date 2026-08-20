# Renomeador de Certidões Estaduais

Este programa localiza o CNPJ em certidões estaduais de layouts diferentes,
consulta a razão social e prepara os documentos para renomeação.

## Fontes aceitas

- Arquivo ZIP contendo PDFs.
- Pasta contendo PDFs.

Ao receber um ZIP, o programa cria outro arquivo compactado e preserva o
original. Ao receber uma pasta, mostra uma prévia e renomeia os PDFs no local
somente após confirmação.

## Identificação do CNPJ

O programa procura um CNPJ válido no texto das três primeiras páginas. Também
confere o nome técnico do arquivo, que é usado como alternativa para PDFs sem
texto pesquisável. Certidões de RJ e RS que informam apenas a raiz do CNPJ são
associadas ao estabelecimento matriz para a consulta da razão social.

## Consulta cadastral

A versão inicial usa o endpoint público de CNPJ da BrasilAPI e, em caso de
indisponibilidade ou bloqueio temporário, usa a API pública do CNPJá como
contingência. O programa respeita o limite divulgado de cinco consultas por
minuto na contingência. Cada CNPJ é consultado somente uma vez e o resultado
fica armazenado no cache local do usuário. A primeira análise precisa de
internet; análises repetidas aproveitam o cache.

Para uso com garantia contratual de disponibilidade e atualização em tempo
real, recomenda-se contratar a API oficial Consulta CNPJ do Serpro e configurar
uma integração autenticada em uma versão futura.

## Segurança

- O ZIP original nunca é sobrescrito.
- A aplicação mostra a razão social e o novo nome antes de gerar o resultado.
- Certidões repetidas recebem `(2)`, `(3)` e assim por diante.
- Arquivos sem CNPJ ou sem resposta cadastral permanecem identificados como
  erro e não recebem uma razão social inventada.
