# Heimdall — Sistema de Controle de Tablets

API para apoiar o controle de tablets de um armário inteligente, com cadastro de professores e equipamentos, reservas por quantidade, autenticação de dispositivos ESP32, recebimento de eventos e consulta de inventário por tags EPC/RFID.

> **Estado do projeto:** o repositório contém uma API backend em FastAPI, um esquema SQL para MySQL e um sketch ESP32 para prototipagem/simulação. Não foi identificado um frontend web/mobile no conteúdo analisado. O firmware `.ino` atual trabalha com leitores RFID e servo localmente e imprime eventos na Serial; a integração de rede entre esse sketch e a API ainda não aparece implementada nele.

## Índice

- [Visão geral](#visão-geral)
- [Funcionalidades identificadas](#funcionalidades-identificadas)
- [Tecnologias](#tecnologias)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Arquitetura](#arquitetura)
- [Pré-requisitos](#pré-requisitos)
- [Configuração do banco de dados](#configuração-do-banco-de-dados)
- [Configuração e execução da API](#configuração-e-execução-da-api)
- [Documentação e verificação da API](#documentação-e-verificação-da-api)
- [Rotas disponíveis](#rotas-disponíveis)
- [Autenticação de dispositivos](#autenticação-de-dispositivos)
- [Regras de reservas](#regras-de-reservas)
- [Inventário e eventos](#inventário-e-eventos)
- [Firmware ESP32 / RFID](#firmware-esp32--rfid)
- [Configurações](#configurações)
- [Segurança e observações importantes](#segurança-e-observações-importantes)
- [Limitações conhecidas](#limitações-conhecidas)
- [Licença](#licença)

## Visão geral

O **Heimdall** foi estruturado para apoiar o gerenciamento de tablets vinculados a um armário inteligente. A API mantém cadastros, aplica regras de reserva, recebe eventos enviados por dispositivos autorizados e registra leituras de inventário.

O banco utiliza identificadores de patrimônio para os tablets e EPCs para relacionar as tags lidas aos equipamentos cadastrados. O backend também prevê dispositivos em modo real ou simulado, registro de contato do dispositivo e histórico dos eventos recebidos.

## Funcionalidades identificadas

- Cadastro, consulta e atualização de professores.
- Cadastro, consulta e atualização de tablets, incluindo patrimônio, EPC, marca, modelo, número de série e status.
- Cadastro e gerenciamento de dispositivos, com ativação/desativação e indicação de simulação.
- Geração de chave para dispositivo e armazenamento do hash SHA-256 dessa chave no banco.
- Recebimento de eventos de crachá, inventário, porta, falha e heartbeat.
- Registro de logs de eventos, com filtros e paginação.
- Detecção de envios repetidos usando `request_id`, retornando a resposta original quando aplicável.
- Registro de snapshots de inventário, incluindo EPCs desconhecidos e indicadores de completude/qualidade.
- Consulta do último inventário válido ou, opcionalmente, do último inventário mesmo que inválido.
- Consulta de disponibilidade e criação/listagem/cancelamento de reservas por quantidade.
- Endpoint de saúde que verifica a API e a conexão com o banco.
- Sketch ESP32 para prototipagem de armário com quatro leitores RFID, servo, chave e LEDs.

Esta lista descreve o que foi encontrado no código analisado; não implica que todas as partes estejam integradas em um fluxo de ponta a ponta.

## Tecnologias

| Tecnologia | Uso identificado |
|---|---|
| Python | Linguagem do backend |
| FastAPI `0.115.6` | API HTTP e documentação OpenAPI |
| Uvicorn `0.34.0` | Servidor ASGI |
| SQLAlchemy `2.0.36` | Conexão e execução de consultas SQL |
| PyMySQL `1.1.1` | Driver MySQL para Python |
| Pydantic Settings `2.7.0` | Leitura de configurações do ambiente |
| MySQL 8.0.16+ | Banco definido pelo script SQL (há uso de `CHECK` e coluna gerada) |
| ESP32 / Arduino C++ | Firmware de prototipagem |
| MFRC522 | Biblioteca para leitores RFID |
| ESP32Servo | Controle do servo no ESP32 |
| Wokwi | Simulação indicada pelo arquivo do projeto |

As versões Python e do Arduino IDE/Core ESP32 não estão fixadas nos arquivos analisados. Use versões compatíveis com as dependências listadas e valide o ambiente em que o projeto será executado.

## Estrutura do repositório

```text
sa_fabiano/
├── README.md
├── schema_mysql.sql
├── backend/
│   ├── .env.example
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py
│       ├── auth.py
│       ├── config.py
│       ├── database.py
│       ├── main.py
│       ├── schemas.py
│       ├── utils.py
│       └── routers/
│           ├── dispositivos.py
│           ├── eventos.py
│           ├── inventarios.py
│           ├── professores.py
│           ├── reservas.py
│           └── tablets.py
└── armário-tablets-rfid/
    ├── diagram.json
    ├── libraries.txt
    ├── wifi-scan.ino
    └── wokwi-project.txt
```

### Responsabilidade dos principais arquivos

- `backend/app/main.py`: cria a aplicação FastAPI, registra os routers e expõe `/health`.
- `backend/app/config.py`: concentra as configurações de banco, regras de reserva e qualidade mínima do inventário.
- `backend/app/database.py`: cria o engine SQLAlchemy e disponibiliza uma sessão por requisição.
- `backend/app/auth.py`: valida o cabeçalho `X-Device-Key` para eventos enviados pelos dispositivos.
- `backend/app/schemas.py`: define os modelos de entrada e saída usados pela API.
- `backend/app/utils.py`: reúne utilitários para erros de duplicidade e atualização de registros.
- `backend/app/routers/`: contém as rotas por domínio.
- `backend/requirements.txt`: lista as dependências Python.
- `backend/.env.example`: exemplo das variáveis de ambiente necessárias.
- `schema_mysql.sql`: script de criação do banco e de suas tabelas.
- `armário-tablets-rfid/wifi-scan.ino`: sketch do ESP32 com leitura RFID, controle local da porta e sinalização.
- `armário-tablets-rfid/diagram.json`: diagrama da montagem usada no projeto de simulação.
- `armário-tablets-rfid/libraries.txt`: bibliotecas Arduino declaradas para o Wokwi.
- `armário-tablets-rfid/wokwi-project.txt`: referência para a simulação Wokwi.

## Arquitetura

O backend segue uma organização por routers:

- **Professores:** identifica professores e seus crachás.
- **Tablets:** mantém os equipamentos e suas tags EPC.
- **Dispositivos:** cadastra os controladores/armários e gerencia sua situação.
- **Reservas:** calcula disponibilidade e controla reservas por quantidade.
- **Eventos:** recebe e registra eventos do dispositivo.
- **Inventários:** permite consultar o último snapshot do armário.

O banco descrito em `schema_mysql.sql` contém tabelas para administradores, dispositivos, professores, tablets, snapshots de inventário, reservas, empréstimos, itens de empréstimo, logs de leitura, ocorrências e auditoria. **A existência de uma tabela no esquema não significa que exista uma rota de API implementada para ela**; por exemplo, não foram encontrados routers específicos para empréstimos, ocorrências ou auditoria.

## Pré-requisitos

- Python compatível com as versões das dependências do backend.
- MySQL **8.0.16 ou superior**, conforme indicado no esquema SQL.
- Git, para clonar o repositório.
- Para a parte embarcada: Arduino IDE ou ambiente compatível com ESP32, placa/ambiente ESP32 e as bibliotecas MFRC522 e ESP32Servo.
- Opcional: conta/acesso ao Wokwi para abrir a simulação indicada no projeto.

## Configuração do banco de dados

> **Atenção:** `schema_mysql.sql` começa com `DROP DATABASE heimdall;`. Esse comando apaga o banco `heimdall` existente antes de recriá-lo. Faça backup e execute apenas em um ambiente descartável/de desenvolvimento se tiver certeza de que pode perder os dados. Para uma instalação real, remova ou adapte o `DROP DATABASE` antes de executar o script.

1. Inicie o MySQL.
2. Revise `schema_mysql.sql` e confirme que a operação destrutiva é apropriada para seu ambiente.
3. Execute o script com um usuário que tenha permissões para criar o banco e as tabelas. Por exemplo, no terminal:

   ```bash
   mysql -u SEU_USUARIO -p < schema_mysql.sql
   ```

4. O script cria o banco `heimdall` com codificação `utf8mb4` e cria as tabelas definidas no arquivo.

O comando acima solicita a senha interativamente. Substitua `SEU_USUARIO` pelo usuário MySQL apropriado; não coloque senhas diretamente no comando.

## Configuração e execução da API

Os comandos abaixo partem da pasta `backend/`.

### 1. Criar e ativar um ambiente virtual

Linux/macOS:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Instalar dependências

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configurar variáveis de ambiente

Crie um arquivo `.env` dentro de `backend/`, usando `.env.example` como referência:

```dotenv
DB_HOST=localhost
DB_PORT=3306
DB_USER=seu_usuario_mysql
DB_PASSWORD=sua_senha_mysql
DB_NAME=heimdall
```

Ajuste os valores conforme sua instalação. A configuração usa `pydantic-settings` com `env_file=".env"`, portanto execute a aplicação a partir da pasta `backend/` para que esse caminho relativo seja resolvido como esperado.

### 4. Iniciar a API

Ainda dentro de `backend/`, com o ambiente virtual ativado:

```bash
uvicorn app.main:app --reload
```

Por padrão, o Uvicorn informa no terminal o endereço local utilizado. Com a configuração padrão, a API costuma ficar acessível em `http://127.0.0.1:8000`.

> `--reload` é útil durante o desenvolvimento. Para produção, utilize uma configuração de implantação adequada e não habilite recarga automática sem necessidade.

## Documentação e verificação da API

Com o servidor em execução, abra:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI: `http://127.0.0.1:8000/openapi.json`
- Verificação de saúde: `http://127.0.0.1:8000/health`

O endpoint `/health` executa `SELECT 1` no banco. Se a API estiver no ar, mas o banco estiver indisponível, a rota retorna HTTP `503`.

Exemplo de verificação via terminal:

```bash
curl http://127.0.0.1:8000/health
```

Resposta esperada quando API e banco estão acessíveis:

```json
{
  "status": "ok"
}
```

## Rotas disponíveis

Os routers encontrados no código são os seguintes. Consulte `/docs` para os modelos completos, campos obrigatórios, tipos e respostas atualizados.

| Método | Caminho | Descrição |
|---|---|---|
| `GET` | `/health` | Verifica a API e a conexão com o banco |
| `POST` | `/professores` | Cadastra um professor |
| `GET` | `/professores` | Lista professores; aceita filtros e paginação |
| `GET` | `/professores/{professor_id}` | Consulta um professor |
| `PATCH` | `/professores/{professor_id}` | Atualiza um professor |
| `POST` | `/tablets` | Cadastra um tablet |
| `GET` | `/tablets` | Lista tablets; aceita filtros e paginação |
| `GET` | `/tablets/{tablet_id}` | Consulta um tablet |
| `PATCH` | `/tablets/{tablet_id}` | Atualiza um tablet |
| `POST` | `/dispositivos` | Cadastra um dispositivo e gera sua chave |
| `GET` | `/dispositivos` | Lista dispositivos; pode filtrar por `ativo` |
| `GET` | `/dispositivos/{dispositivo_id}` | Consulta um dispositivo |
| `PATCH` | `/dispositivos/{dispositivo_id}` | Atualiza dados/estado de um dispositivo |
| `GET` | `/reservas/disponibilidade` | Consulta a disponibilidade em uma janela de tempo |
| `POST` | `/reservas` | Cria uma reserva |
| `GET` | `/reservas` | Lista reservas com filtros disponíveis |
| `GET` | `/reservas/{reserva_id}` | Consulta uma reserva |
| `POST` | `/reservas/{reserva_id}/cancelar` | Cancela uma reserva |
| `POST` | `/eventos` | Recebe evento de um dispositivo autenticado |
| `GET` | `/eventos` | Consulta logs de eventos com filtros e paginação |
| `GET` | `/inventarios/ultimo` | Consulta o último inventário de um dispositivo |

### Observações sobre os endpoints

- Os endpoints de listagem de professores, tablets, reservas e eventos possuem parâmetros de consulta; os limites e filtros exatos estão documentados no Swagger.
- `GET /inventarios/ultimo` exige `dispositivo_id` e aceita `apenas_validos` (padrão `true`).
- `POST /eventos` exige o cabeçalho `X-Device-Key`.
- O cadastro de dispositivo retorna uma chave no momento da criação. Guarde-a com segurança: o código mostrado gera a chave uma vez e persiste somente seu hash.
- Não há autenticação geral de usuário aplicada a todas as rotas administrativas nos routers analisados. Não exponha a API publicamente sem implementar e configurar os controles de acesso apropriados.

## Autenticação de dispositivos

Para o recebimento de eventos, o backend espera o cabeçalho:

```http
X-Device-Key: CHAVE_DO_DISPOSITIVO
```

O código calcula o hash SHA-256 da chave recebida e procura o hash correspondente na tabela `dispositivos`. Uma chave ausente ou inválida resulta em `401`; um dispositivo inativo resulta em `403`. Chamadas autenticadas atualizam o horário do último contato e o IP observado.

A chave em texto puro é devolvida na criação do dispositivo; o banco armazena seu hash. Se a chave for perdida, não conte com a possibilidade de recuperá-la do banco.

## Regras de reservas

Pelas regras implementadas no backend:

- A reserva é feita por **quantidade de tablets**, não por um tablet individual específico.
- O início não pode estar mais de cinco minutos no passado (margem para pequenas diferenças ao informar o horário).
- O início deve respeitar a antecedência máxima configurada, cujo padrão no código é de 24 horas.
- O sistema considera a capacidade como o número de tablets cujo status não seja `manutencao` nem `indisponivel`.
- Reservas sobrepostas para o mesmo dispositivo são avaliadas pelo pico de quantidade reservada durante a janela consultada.
- Reservas ativas podem expirar quando passam da tolerância após o início (padrão de 30 minutos) ou quando chegam ao fim; a expiração é atualizada durante o uso dos endpoints de reserva.

A capacidade é global no banco porque o esquema/código atual ainda não associa cada tablet fisicamente a um armário específico. Se houver vários armários independentes, essa regra precisa ser revista.

## Inventário e eventos

`POST /eventos` recebe tipos de evento definidos pelos modelos Pydantic, incluindo crachá, inventário, porta, falha e heartbeat.

No inventário, o backend registra informações como:

- identificador do pedido (`request_id`);
- EPCs recebidos e EPCs não cadastrados;
- indicação de leitura completa;
- qualidade informada e quantidade de leituras;
- horário da leitura e do recebimento;
- resultado e motivo de invalidação, quando aplicável.

O inventário é considerado inválido se a leitura estiver incompleta ou se a qualidade informada ficar abaixo do limite configurado. O padrão de `inventario_qualidade_minima` é `0.8`. Snapshots inválidos são registrados, mas a consulta padrão do último inventário retorna apenas snapshots válidos; use `apenas_validos=false` para incluir os inválidos.

O campo `request_id` é usado para reconhecer reenvios. Quando o mesmo dispositivo envia novamente um pedido já registrado, a API tenta devolver a resposta anterior com `repetido=true`, evitando processar o evento duas vezes.

## Firmware ESP32 / RFID

A pasta `armário-tablets-rfid/` contém um sketch de protótipo com:

- ESP32;
- quatro leitores RFID MFRC522: três posições de tablets e um leitor para crachá;
- servo para o mecanismo da porta;
- chave física;
- LED indicador de destravamento;
- LED de alerta;
- mensagens de estado e inventário na Serial.

O sketch usa um cadastro demonstrativo de três tablets (`TAB-001`, `TAB-002`, `TAB-003`) com UIDs de exemplo. Esses valores devem ser substituídos pelos identificadores adequados ao hardware usado.

O comportamento implementado no sketch inclui detecção de presença de tags, atualização local do inventário, acionamento do servo, indicação de porta destravada/travada e alerta quando há movimentação de um slot com a porta travada.

### Bibliotecas

O arquivo `libraries.txt` declara:

- `MFRC522`
- `ESP32Servo`

O arquivo `wokwi-project.txt` aponta para a simulação publicada no Wokwi. O firmware atualmente apresentado não contém configuração de Wi-Fi, cliente HTTP ou envio de eventos para a API. Portanto, a comunicação entre o protótipo físico/simulado e o backend ainda precisa ser desenvolvida e validada antes de considerar o sistema integrado.

## Configurações

As configurações identificadas em `backend/app/config.py` são:

| Variável | Padrão no código | Finalidade |
|---|---:|---|
| `DB_HOST` | `localhost` | Host do MySQL |
| `DB_PORT` | `3306` | Porta do MySQL |
| `DB_USER` | `heimdall` | Usuário do banco |
| `DB_PASSWORD` | vazio no código | Senha do banco |
| `DB_NAME` | `heimdall` | Nome do banco |
| `RESERVA_ANTECEDENCIA_MAX_HORAS` | `24` | Antecedência máxima de reserva |
| `RESERVA_TOLERANCIA_MINUTOS` | `30` | Tolerância de reserva |
| `INVENTARIO_QUALIDADE_MINIMA` | `0.8` | Qualidade mínima para considerar o inventário válido |

As configurações de reserva e inventário são valores padrão definidos pela classe de settings. Para ambientes diferentes, configure as variáveis correspondentes e valide o comportamento no ambiente de execução.

## Segurança e observações importantes

- **Não publique credenciais:** mantenha o arquivo `.env` fora do controle de versão. Use `.env.example` apenas com valores fictícios.
- **Verifique o histórico do Git:** se alguma senha, token ou chave real já foi commitada, remover o arquivo em um commit posterior não apaga o segredo do histórico. Troque/rotacione a credencial exposta e limpe o histórico se necessário.
- **Não exponha o banco:** restrinja o acesso de rede ao MySQL e utilize um usuário com permissões mínimas.
- **Proteja a API:** as rotas de cadastro e atualização não apresentam autenticação de usuário geral no código analisado. Antes de disponibilizar a API fora de um ambiente local/confiável, implemente autenticação, autorização e HTTPS.
- **Revise o script SQL:** o `DROP DATABASE heimdall` pode causar perda de dados.
- **Use chaves únicas por dispositivo:** trate `X-Device-Key` como segredo e não o registre em logs públicos.
- **Valide o firmware em bancada:** o sketch é um protótipo e usa UIDs de exemplo; confirme pinagem, alimentação, comportamento dos leitores e do servo no hardware real.
- **Não presuma integração completa:** a API e o firmware aparecem no mesmo repositório, mas o sketch atual não envia dados à API.

## Limitações conhecidas

Com base nos arquivos analisados:

1. Não foi encontrado frontend web ou mobile.
2. O firmware ESP32 não implementa comunicação Wi-Fi/HTTP com o backend.
3. O código contém tabelas de empréstimos, itens de empréstimo, ocorrências e auditoria no esquema SQL, mas não foram encontrados routers correspondentes para todas essas áreas.
4. O esquema SQL apaga e recria o banco `heimdall` ao ser executado sem alterações.
5. Não foram identificados testes automatizados no conjunto principal de arquivos analisado.
6. A aplicação usa `datetime.now()` e configurações de data/hora sem uma estratégia de fuso horário explicitamente documentada; confirme a política de horário antes de uso em produção.

## Licença

Não foi identificada uma licença no conjunto de arquivos analisado. Se o projeto for destinado a distribuição pública, adicione um arquivo `LICENSE` com a licença escolhida antes de declarar condições de reutilização.

---

Documentação elaborada a partir da estrutura e dos arquivos presentes no repositório fornecido. Confirme as instruções no ambiente de implantação antes de utilizar o sistema em produção.
