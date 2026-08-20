# Distribuição do executável

O arquivo pronto para uso é:

```text
dist\RenomeadorRelatoriosFiscais.exe
```

Compartilhe somente esse arquivo com os demais usuários. Eles não precisam
receber o código-fonte, instalar Python ou instalar bibliotecas.

## Como usar em outro computador

1. Copie `RenomeadorRelatoriosFiscais.exe` para uma pasta local.
2. Abra o executável com dois cliques.
3. Escolha a pasta que contém os relatórios PDF.
4. Confira a prévia e clique em **Renomear arquivos**.

O executável é compatível com Windows de 64 bits.

## Aviso do Windows

Como o arquivo ainda não possui uma assinatura digital comprada de uma
autoridade certificadora, o Windows pode exibir o aviso do SmartScreen na
primeira execução. Para distribuição interna, confirme que o arquivo veio da
pasta oficial do escritório antes de autorizar a execução.

## Gerar uma versão nova

Depois de alterar o sistema, execute `gerar_executavel.bat`. A nova versão será
criada novamente dentro da pasta `dist`.
