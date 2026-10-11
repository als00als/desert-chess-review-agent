# Unity 코드 리뷰 리포트

## 1. 요약

| 항목 | 값 |
| --- | --- |
| 리뷰 파일 | 5개 (167줄, 배치 1개) |
| 리뷰어 | 버그, 성능, Unity 안티패턴 |
| 리뷰어 지적 → 최종 | 25건 → **17건** (검증 기각 0, 병합 8) |
| 등급별 | P0 4 · P1 4 · P2 7 · P3 2 |
| 분류별 | 버그 7 · 성능 3 · Unity 7 |
| 소요 시간 · 토큰 | 85.4초 · 59,563 토큰 (gpt-5.6-luna) |

## 2. 총평

가장 시급한 문제는 순회 중 컬렉션 수정, 필수 컴포넌트 미할당, 탄약 부족 상태에서의 배열 인덱스 초과 등 P0 런타임 예외로, 우선 실행 흐름이 중단되지 않도록 방어 로직과 사전 검증을 적용해야 한다.  
다음으로 static 이벤트 해제, 파괴된 Unity 오브젝트 처리, 싱글턴 중복 인스턴스 및 정적 참조, 부모 오브젝트의 `DontDestroyOnLoad` 문제를 정리해 객체 수명주기와 씬 전환 안정성을 확보해야 한다.  
이후 HUD와 플레이어 코드에 반복되는 매 프레임 검색·컴포넌트 조회·문자열 생성·UI 갱신을 제거하고, Rigidbody2D 이동은 물리 시간 기준으로 조정해야 한다.  
마지막으로 태그 문자열 비교와 공개 체력 필드 노출을 개선해 유지보수성과 데이터 캡슐화를 강화해야 한다.

## 3. 지적 목록

### P0 즉시 수정 (크래시·진행 불가) — 4건

#### BUG-001 · foreach 순회 중 nearbyAllies를 수정해 InvalidOperationException 발생
- 위치: `EnemySeed.cs:30-35` · 분류: 버그 (+Unity 안티패턴) · Jev 0.84
- 이유: foreach로 순회 중인 nearbyAllies에서 항목을 제거하므로 일치하는 동료가 있으면 열거 상태가 무효화되고, 다음 순회 단계에서 InvalidOperationException이 발생합니다.
- 수정 제안: 순회 없이 직접 제거하세요: `nearbyAllies.Remove(dead);` 또는 조건에 맞는 항목을 모두 제거해야 한다면 `nearbyAllies.RemoveAll(ally => ally == dead);`를 사용하세요.

```csharp
foreach (EnemySeed ally in nearbyAllies)
{
    if (ally == dead)
    {
        nearbyAllies.Remove(ally);
    }
}
```

#### BUG-002 · Rigidbody2D 참조가 없을 때 즉시 예외가 발생함
- 위치: `PlayerSeed.cs:16-17` · 분류: 버그 · Jev 0.91
- 이유: 같은 GameObject에 Rigidbody2D가 없으면 GetComponent<Rigidbody2D>()가 null을 반환하고, 이어지는 MovePosition 호출에서 NullReferenceException이 발생합니다.
- 수정 제안: Rigidbody2D를 필수 컴포넌트로 보장하고 초기화 시 검증하세요. 예를 들어 클래스에 [RequireComponent(typeof(Rigidbody2D))]를 추가한 뒤 Awake에서 참조를 캐싱하고, 누락 시 명확한 오류를 출력합니다.

```csharp
Rigidbody2D body = GetComponent<Rigidbody2D>();
body.MovePosition(body.position + input * moveSpeed);
```

#### BUG-003 · Animator 미할당 시 NullReferenceException 발생
- 위치: `PlayerSeed.cs:19-20` · 분류: 버그 · Jev 0.81
- 이유: 인스펙터에서 SerializeField인 animator가 할당되지 않으면 매 프레임 SetBool 호출 시 NullReferenceException이 발생해 해당 동작이 중단됩니다.
- 수정 제안: 필수 참조라면 Awake에서 animator 할당 여부를 검증하고 누락 시 명확한 오류를 내거나, 선택적 참조라면 null 검사 후 SetBool을 호출하세요.

```csharp
bool firing = Input.GetMouseButton(0);
animator.SetBool("IsFire", firing);
```

#### UNITY-001 · 탄약이 없을 때 Fire 호출 시 배열 인덱스 초과
- 위치: `WeaponSeed.cs:17-21` · 분류: Unity 안티패턴 (+버그) · Jev 0.77
- 이유: usesLeft가 0인 상태에서도 public 메서드인 Fire()를 직접 호출할 수 있습니다. 현재 usesLeft를 먼저 감소시켜 -1로 만든 뒤 projectilePrefabs[-1]에 접근하므로 IndexOutOfRangeException이 발생합니다.
- 수정 제안: Fire() 시작 시 CanFire를 확인하고, 발사 불가하면 즉시 반환하세요. 이후에만 usesLeft를 감소시키고 배열에 접근해야 합니다.

```csharp
public void Fire()
{
    usesLeft--;
    GameObject prefab = projectilePrefabs[usesLeft];
    Instantiate(prefab, transform.position, transform.rotation);
}
```


### P1 잘못된 동작 — 4건

#### BUG-004 · static 이벤트 구독 해제로 중복 호출 및 파괴된 객체 참조 방지
- 위치: `EnemySeed.cs:17-20` · 분류: 버그 (+Unity 안티패턴) · Jev 0.85
- 이유: OnEnable에서 static 이벤트를 구독하지만 OnDisable 또는 OnDestroy에서 해제하지 않습니다. 오브젝트를 비활성화 후 재활성화하면 핸들러가 중복 등록되고, 파괴된 EnemySeed가 이벤트에 남아 이후 호출될 수 있습니다.
- 수정 제안: OnDisable에서 동일한 핸들러를 해제하세요: `private void OnDisable() { OnAnyEnemyDied -= HandleAllyDied; }`

```csharp
private void OnEnable()
{
    OnAnyEnemyDied += HandleAllyDied;
}
```

#### UNITY-002 · 파괴된 Unity 오브젝트에 null 조건 연산자를 사용함
- 위치: `EnemySeed.cs:24` · 분류: Unity 안티패턴 · Jev 0.76
- 이유: UnityEngine.Object는 파괴된 뒤에도 C# 참조 자체가 null이 아닐 수 있어 ?.가 Unity의 가짜 null을 처리하지 못합니다. 파괴된 target에 접근하면 MissingReferenceException이 발생할 수 있습니다.
- 수정 제안: Unity 오브젝트는 명시적으로 확인하고, 참조 수명도 함께 관리합니다.
```csharp
Vector3 goal = target != null ? target.position : transform.position;
```

```csharp
Vector3 goal = target?.position ?? transform.position;
```

#### BUG-005 · 싱글턴 중복 인스턴스 및 정적 참조 관리 누락
- 위치: `GameManagerSeed.cs:16` · 분류: 버그 (+Unity 안티패턴) · Jev 0.85
- 이유: Awake에서 기존 Instance를 확인하지 않고 현재 객체를 대입하므로 씬 중복 로드나 중복 배치 시 여러 GameManagerSeed가 생성되고 Instance가 새 객체로 덮어써집니다. 또한 객체가 파괴될 때 정적 참조를 정리하는 처리도 없습니다.
- 수정 제안: 기존 인스턴스가 있으면 현재 객체를 즉시 파괴하고, 최초 인스턴스만 Instance에 등록하십시오. 필요하다면 OnDestroy에서 Instance가 자신을 가리킬 때 null로 정리합니다.
```csharp
private void Awake()
{
    if (Instance != null && Instance != this)
    {
        Destroy(gameObject);
        return;
    }

    Instance = this;
    DontDestroyOnLoad(gameObject);
    currentRound = startRound;
}

private void OnDestroy()
{
    if (Instance == this)
        Instance = null;
}
```

```csharp
Instance = this;
```

#### UNITY-003 · 부모가 있는 오브젝트에 DontDestroyOnLoad 호출
- 위치: `GameManagerSeed.cs:16-17` · 분류: Unity 안티패턴 · Jev 0.50
- 이유: GameManagerSeed가 부모 오브젝트의 자식이면 DontDestroyOnLoad가 루트 오브젝트에만 적용되므로 호출이 무시될 수 있습니다. 그 결과 씬 전환 시 매니저가 파괴됩니다.
- 수정 제안: GameManagerSeed를 루트 오브젝트로 이동하거나, 부모 계층 전체를 유지해야 한다면 루트 오브젝트에 DontDestroyOnLoad를 호출하십시오.
```csharp
DontDestroyOnLoad(transform.root.gameObject);
```
단, 루트에 다른 씬 전용 오브젝트가 포함되어 있다면 매니저 전용 루트 오브젝트를 별도로 구성하는 것이 안전합니다.

```csharp
Instance = this;
DontDestroyOnLoad(gameObject);
```


### P2 성능·잠재 버그 — 7건

#### BUG-006 · Update에서 매 프레임 FindObjectOfType로 씬 전체를 검색함
- 위치: `HudSeed.cs:10-13` · 분류: 버그 (+성능, Unity 안티패턴) · Jev 0.91
- 이유: HudSeed의 Update마다 FindObjectOfType<PlayerHealthSeed>()를 호출해 씬 전체 검색 비용이 반복됩니다. 동일한 참조를 매 프레임 다시 찾을 필요가 없습니다.
- 수정 제안: PlayerHealthSeed를 SerializeField로 주입하거나 Awake/Start에서 한 번만 찾아 캐싱하세요. 가능하다면 체력 변경 이벤트를 구독해 변경 시점에만 UI를 갱신하세요.

```csharp
private void Update()
{
    PlayerHealthSeed health = FindObjectOfType<PlayerHealthSeed>();
    hpLabel.text = $"HP {health.Current} / {health.Max}";
}
```

#### BUG-007 · PlayerHealthSeed와 hpLabel의 null 가능성을 검사하지 않음
- 위치: `HudSeed.cs:12-13` · 분류: 버그 · Jev 0.93
- 이유: 씬에 PlayerHealthSeed가 없으면 FindObjectOfType이 null을 반환하고, hpLabel이 할당되지 않은 경우에도 참조 접근 시 NullReferenceException이 발생할 수 있습니다.
- 수정 제안: PlayerHealthSeed와 hpLabel을 SerializeField로 명시적으로 연결하고 Awake 또는 OnValidate에서 필수 참조를 검증하세요. 런타임에서는 null 여부를 확인한 뒤 안전하게 종료하거나 오류를 명확히 보고하세요.

```csharp
PlayerHealthSeed health = FindObjectOfType<PlayerHealthSeed>();
hpLabel.text = $"HP {health.Current} / {health.Max}";
```

#### PERF-001 · 변경되지 않은 HP UI를 매 프레임 갱신해 문자열과 UI 비용이 발생함
- 위치: `HudSeed.cs:13` · 분류: 성능 · Jev 0.87
- 이유: HP가 바뀌지 않은 프레임에도 문자열 보간과 Text 갱신을 반복합니다. 이로 인해 불필요한 문자열 생성 및 GC 할당과 UI 처리 비용이 발생합니다.
- 수정 제안: Update 폴링을 제거하고 HP 변경 이벤트나 명시적인 SetHealth(current, max) 호출을 통해 체력이 변경될 때만 문자열을 생성하고 hpLabel.text를 갱신하세요.

```csharp
hpLabel.text = $"HP {health.Current} / {health.Max}";
```

#### PERF-002 · Update에서 GetComponent를 매 프레임 호출함
- 위치: `PlayerSeed.cs:16` · 분류: 성능 (+Unity 안티패턴) · Jev 0.70
- 이유: Update마다 Rigidbody2D를 검색해 불필요한 반복 비용이 발생합니다. 컴포넌트 참조는 초기화 시 한 번만 가져와 재사용해야 합니다.
- 수정 제안: private Rigidbody2D body를 선언하고 Awake 또는 Start에서 GetComponent<Rigidbody2D>() 결과를 캐싱한 뒤 Update와 FixedUpdate에서 재사용하세요.

```csharp
Rigidbody2D body = GetComponent<Rigidbody2D>();
```

#### UNITY-004 · Rigidbody2D 이동을 Update에서 수행함
- 위치: `PlayerSeed.cs:16-17` · 분류: Unity 안티패턴 · Jev 0.82
- 이유: MovePosition은 물리 이동이므로 Update에서 호출하면 물리 프레임과 실행 프레임의 차이에 따라 이동 처리가 일관되지 않을 수 있습니다.
- 수정 제안: Rigidbody2D 참조를 캐싱하고 이동 코드를 FixedUpdate로 옮기세요. 입력값은 Update에서 읽어 저장하고 FixedUpdate에서 해당 값을 사용하면 됩니다.

```csharp
Rigidbody2D body = GetComponent<Rigidbody2D>();
body.MovePosition(body.position + input * moveSpeed);
```

#### UNITY-005 · Rigidbody2D 이동량에 물리 시간 간격을 반영하지 않음
- 위치: `PlayerSeed.cs:17` · 분류: Unity 안티패턴 · Jev 0.90
- 이유: moveSpeed를 프레임 간 이동 거리로 직접 사용해 고정 물리 프레임 기준의 속도가 보장되지 않으며, 설정된 이동 속도 해석이 부정확해질 수 있습니다.
- 수정 제안: FixedUpdate에서 MovePosition을 호출한다면 이동량에 Time.fixedDeltaTime을 곱하세요: body.MovePosition(body.position + input * moveSpeed * Time.fixedDeltaTime);

```csharp
body.MovePosition(body.position + input * moveSpeed);
```

#### PERF-003 · Animator 파라미터 이름을 매 프레임 문자열로 전달
- 위치: `PlayerSeed.cs:19-20` · 분류: 성능 · Jev 0.64
- 이유: Update 등 매 프레임 실행되는 코드에서 문자열 기반 Animator 파라미터를 반복 전달하므로 불필요한 파라미터 이름 처리 비용이 발생할 수 있습니다.
- 수정 제안: `private static readonly int IsFireHash = Animator.StringToHash("IsFire");`로 해시를 캐싱한 뒤 `animator.SetBool(IsFireHash, firing);`를 사용하세요.

```csharp
bool firing = Input.GetMouseButton(0);
animator.SetBool("IsFire", firing);
```


### P3 유지보수 — 2건

#### UNITY-006 · tag 문자열 비교를 사용함
- 위치: `HudSeed.cs:18` · 분류: Unity 안티패턴 · Jev 0.63
- 이유: Unity의 tag 비교 방식이 아니며, 태그 오타를 컴파일 단계에서 검출하지 못합니다.
- 수정 제안: ```csharp
if (other.CompareTag("Player"))
```

```csharp
if (other.gameObject.tag == "Player")
```

#### UNITY-007 · 체력 값을 public 필드로 노출함
- 위치: `HudSeed.cs:25-29` · 분류: Unity 안티패턴 · Jev 0.81
- 이유: 외부 코드나 Inspector에서 체력 값을 제한 없이 직접 변경할 수 있어 상태 변경 경로가 통제되지 않습니다.
- 수정 제안: ```csharp
[SerializeField] private int max = 10;
private int current = 10;

public int Current => current;
public int Max => max;
```

```csharp
public class PlayerHealthSeed : MonoBehaviour
{
    public int Current = 10;
    public int Max = 10;
}
```


## 4. 파일별 요약

| 파일 | 줄 | P0 | P1 | P2 | P3 |
| --- | --- | --- | --- | --- | --- |
| `EnemySeed.cs` | 49 | 1 | 2 | 0 | 0 |
| `GameManagerSeed.cs` | 29 | 0 | 2 | 0 | 0 |
| `HudSeed.cs` | 30 | 0 | 0 | 3 | 2 |
| `PlayerSeed.cs` | 23 | 2 | 0 | 4 | 0 |
| `WeaponSeed.cs` | 36 | 1 | 0 | 0 | 0 |

지적 없는 파일: 0개

## 5. 부록: 검증에서 기각된 지적

없음
