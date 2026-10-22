#include <SPI.h>
#include <MFRC522.h>
#include <ESP32Servo.h>

const uint8_t NUM_TABLETS = 3;
const uint8_t IDX_CRACHA = 3;
const uint8_t NUM_LEITORES = 4;

const uint8_t PINO_RST = 21;
const uint8_t PINO_SERVO = 13;
const uint8_t PINO_CHAVE = 27;
const uint8_t LED_DESTRAVADO = 25;
const uint8_t LED_ALERTA = 26;

const int ANGULO_FECHADA = 0;
const int ANGULO_ABERTA = 90;
const unsigned long TIMEOUT_SEM_SINAL = 500;

// Cadastro: codigo do tablet e UID do cartao dele (edite aqui)
struct Tablet {
  const char* codigo;
  const char* uid;
};
const Tablet CADASTRO[NUM_TABLETS] = {
  {"TAB-001", "01:02:03:04"},
  {"TAB-002", "11:22:33:44"},
  {"TAB-003", "55:66:77:88"}
};

MFRC522 leitores[NUM_LEITORES] = {
  MFRC522(5,  MFRC522::UNUSED_PIN),
  MFRC522(16, MFRC522::UNUSED_PIN),
  MFRC522(17, MFRC522::UNUSED_PIN),
  MFRC522(22, MFRC522::UNUSED_PIN)
};

Servo porta;

unsigned long ultimoSinal[NUM_LEITORES];
bool registrado[NUM_TABLETS];   // inventario oficial
bool violacao[NUM_TABLETS];     // mudanca com porta travada
String uidSlot[NUM_TABLETS];    // ultimo UID visto em cada slot
int ultimaContagem = -1;

bool destravada = false;
bool portaAberta = false;
bool crachaAnterior = false;
bool chaveAnterior = false;

String uidParaTexto(MFRC522::Uid &u) {
  String s = "";
  for (byte i = 0; i < u.size; i++) {
    if (i > 0) s += ":";
    if (u.uidByte[i] < 0x10) s += "0";
    s += String(u.uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;
}

String nomeDoUid(const String &uid) {
  for (uint8_t i = 0; i < NUM_TABLETS; i++) {
    if (uid.equalsIgnoreCase(CADASTRO[i].uid)) return String(CADASTRO[i].codigo);
  }
  if (uid.length() > 0) return String("DESCONHECIDO(") + uid + ")";
  return String("SEM-LEITURA");
}

// Presenca = WakeupA responde (sem HaltA, por causa do simulador).
// Se responder, tenta ler o UID.
bool lerTag(MFRC522 &leitor, String &uid) {
  byte atqa[2];
  byte tam = sizeof(atqa);
  MFRC522::StatusCode st = leitor.PICC_WakeupA(atqa, &tam);
  if (st != MFRC522::STATUS_OK && st != MFRC522::STATUS_COLLISION) {
    return false;
  }
  if (leitor.PICC_ReadCardSerial()) {
    uid = uidParaTexto(leitor.uid);
  }
  return true;
}

void imprimirInventario() {
  Serial.println("--- Inventario ---");
  for (uint8_t i = 0; i < NUM_TABLETS; i++) {
    Serial.print("Slot ");
    Serial.print(i + 1);
    Serial.print(": ");
    Serial.print(nomeDoUid(uidSlot[i]));
    Serial.println(registrado[i] ? " - NO ARMARIO" : " - FORA");
  }
  Serial.println("------------------");
}

void setup() {
  Serial.begin(115200);

  pinMode(LED_DESTRAVADO, OUTPUT);
  pinMode(LED_ALERTA, OUTPUT);
  pinMode(PINO_CHAVE, INPUT_PULLUP);

  pinMode(PINO_RST, OUTPUT);
  digitalWrite(PINO_RST, HIGH);

  SPI.begin(18, 19, 23);

  for (uint8_t i = 0; i < NUM_LEITORES; i++) {
    leitores[i].PCD_Init();
    ultimoSinal[i] = 0;
  }

  for (uint8_t i = 0; i < NUM_TABLETS; i++) {
    registrado[i] = false;
    violacao[i] = false;
    uidSlot[i] = "";
  }

  porta.attach(PINO_SERVO, 500, 2400);
  porta.write(ANGULO_FECHADA);

  Serial.println("Armario de tablets iniciado.");
}

void atualizarTablets() {
  unsigned long agora = millis();
  bool liberada = destravada;
  bool alarme = false;
  int contagem = 0;

  for (uint8_t i = 0; i < NUM_TABLETS; i++) {
    String uid = "";
    if (lerTag(leitores[i], uid)) {
      ultimoSinal[i] = agora;
      if (uid.length() > 0) uidSlot[i] = uid;
    }

    bool fisico = ultimoSinal[i] != 0 &&
                  (agora - ultimoSinal[i]) < TIMEOUT_SEM_SINAL;

    if (fisico != registrado[i]) {
      if (liberada) {
        // Porta liberada: registra a movimentacao
        registrado[i] = fisico;
        violacao[i] = false;
        Serial.print("Slot ");
        Serial.print(i + 1);
        Serial.print(": ");
        Serial.print(nomeDoUid(uidSlot[i]));
        Serial.println(fisico ? " DEVOLVIDO" : " RETIRADO");

        if (fisico && !uidSlot[i].equalsIgnoreCase(CADASTRO[i].uid)) {
          Serial.print("  Aviso: este slot e do ");
          Serial.println(CADASTRO[i].codigo);
        }
      } else if (!violacao[i]) {
        // Porta travada: nao registra, dispara alarme
        violacao[i] = true;
        Serial.print("ALERTA! Slot ");
        Serial.print(i + 1);
        Serial.print(" (");
        Serial.print(nomeDoUid(uidSlot[i]));
        Serial.println(") movimentado com a porta TRAVADA");
      }
    } else if (violacao[i]) {
      violacao[i] = false;
      Serial.print("Slot ");
      Serial.print(i + 1);
      Serial.println(": alarme encerrado");
    }

    if (violacao[i]) alarme = true;
    if (registrado[i]) contagem++;
  }

  if (contagem != ultimaContagem) {
    ultimaContagem = contagem;
    Serial.print("Tablets no armario: ");
    Serial.print(contagem);
    Serial.print("/");
    Serial.println(NUM_TABLETS);
  }

  if (alarme) {
    digitalWrite(LED_ALERTA, (millis() / 150) % 2);
  } else {
    digitalWrite(LED_ALERTA, contagem < NUM_TABLETS ? HIGH : LOW);
  }
}

void atualizarPorta() {
  unsigned long agora = millis();

  String uid = "";
  if (lerTag(leitores[IDX_CRACHA], uid)) {
    ultimoSinal[IDX_CRACHA] = agora;
  }
  bool crachaPresente = ultimoSinal[IDX_CRACHA] != 0 &&
                        (agora - ultimoSinal[IDX_CRACHA]) < TIMEOUT_SEM_SINAL;

  bool chaveLigada = digitalRead(PINO_CHAVE) == LOW;

  bool crachaChegou = crachaPresente && !crachaAnterior;
  bool crachaSaiu = !crachaPresente && crachaAnterior;

  if (crachaChegou && !destravada) {
    destravada = true;
    Serial.println("Cracha detectado: porta DESTRAVADA");
  }

  if (crachaSaiu && destravada && !portaAberta) {
    destravada = false;
    Serial.println("Cracha removido: porta TRAVADA");
    imprimirInventario();
  }

  if (chaveLigada && !portaAberta) {
    if (destravada) {
      porta.write(ANGULO_ABERTA);
      portaAberta = true;
      Serial.println("Porta ABERTA");
    } else if (!chaveAnterior) {
      Serial.println("Porta travada: acesso negado (passe o cracha)");
    }
  }

  if (!chaveLigada && portaAberta) {
    porta.write(ANGULO_FECHADA);
    portaAberta = false;
    destravada = false;
    Serial.println("Porta FECHADA e TRAVADA");
    imprimirInventario();
  }

  digitalWrite(LED_DESTRAVADO, destravada ? HIGH : LOW);

  crachaAnterior = crachaPresente;
  chaveAnterior = chaveLigada;
}

void loop() {
  atualizarTablets();
  atualizarPorta();
  delay(20);
}