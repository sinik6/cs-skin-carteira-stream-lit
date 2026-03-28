# Fork Setup

Esta pasta ja esta pronta como base git correta:

- caminho: `C:\Users\Administrator\Downloads\cs-skin-carteira-stream-lit-jr\cs-skin-carteira-stream-lit-fork-ready`
- remote atual: `origin = https://github.com/jpjamal/cs-skin-carteira-stream-lit.git`
- suas modificacoes locais ja estao aplicadas aqui

## 1. Crie seu fork no GitHub

Abra:

`https://github.com/jpjamal/cs-skin-carteira-stream-lit`

Clique em `Fork` e crie o repositorio na sua conta.

Exemplo de fork:

`https://github.com/SEU_USUARIO/cs-skin-carteira-stream-lit`

## 2. Entre nesta pasta no terminal

```powershell
cd C:\Users\Administrator\Downloads\cs-skin-carteira-stream-lit-jr\cs-skin-carteira-stream-lit-fork-ready
```

## 3. Troque o remote `origin` para o seu fork

```powershell
git remote rename origin upstream
git remote add origin https://github.com/SEU_USUARIO/cs-skin-carteira-stream-lit.git
git remote -v
```

Resultado esperado:

- `origin` = seu fork
- `upstream` = repositorio do dono

## 4. Crie sua branch de trabalho

```powershell
git checkout -b minha-versao
```

## 5. Faça o commit das alteracoes

```powershell
git add .
git commit -m "Customize price estimation, cache safety, and portfolio UI"
```

## 6. Envie para o seu fork

```powershell
git push -u origin minha-versao
```

## 7. Atualize sua base no futuro

Para puxar mudancas novas do dono:

```powershell
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```

Para atualizar sua branch com a base nova:

```powershell
git checkout minha-versao
git merge main
```

Se preferir historico mais limpo:

```powershell
git checkout minha-versao
git rebase main
```
