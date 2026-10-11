# Unity 코드 리뷰 리포트

## 1. 요약

| 항목 | 값 |
| --- | --- |
| 리뷰 파일 | 5개 (172줄, 배치 1개) |
| 리뷰어 | 버그, 성능, Unity 안티패턴 |
| 리뷰어 지적 → 최종 | 22건 → **14건** (검증 기각 0, 병합 8) |
| 등급별 | P0 0 · P1 6 · P2 6 · P3 2 |
| 분류별 | 버그 4 · 성능 4 · Unity 6 |
| 소요 시간 · 토큰 | 72.2초 · 56,956 토큰 (gpt-5.6-luna) |

## 2. 총평

가장 시급한 문제는 P1 항목에 집중되어 있으며, 이벤트 구독 해제 누락과 파괴된 Unity 객체 처리 오류, 컬렉션 순회 중 수정, 무기 배열 범위 초과가 런타임 장애를 일으킬 수 있다.  
또한 `GameManagerSeed`의 싱글턴 중복 생성 시 인스턴스 덮어쓰기와 부모가 있는 오브젝트에 대한 `DontDestroyOnLoad` 호출을 우선 정리해야 한다.  
반복되는 패턴으로는 `Update`에서의 객체 검색·컴포넌트 조회·UI 폴링·문자열 생성·Animator 문자열 사용이 있으며, 이를 캐싱하고 변경 시점 기반 갱신으로 전환하는 작업이 P2 개선 순서다.  
이후 이동 처리의 프레임 의존성을 보완하고, 태그 비교 방식과 체력 필드 노출 같은 P3 코드 품질 항목을 정리하는 순서가 적절하다.

## 3. 지적 목록

### P1 잘못된 동작 — 6건

#### BUG-001 · 정적 사망 이벤트 구독 해제 누락
- 위치: `EnemySeed.cs:17-20` · 분류: 버그 (+Unity 안티패턴) · Jev 0.88
- 이유: OnEnable에서 static 이벤트에 HandleAllyDied를 구독하지만 OnDisable 또는 OnDestroy에서 해제하지 않습니다. 그 결과 비활성화·파괴된 객체가 이벤트에 계속 남고, 재활성화할 때마다 동일 핸들러가 중복 등록되어 이후 사망 이벤트가 여러 번 처리될 수 있습니다.
- 수정 제안: OnDisable에서 `OnAnyEnemyDied -= HandleAllyDied;`를 호출해 구독을 해제하세요. OnEnable/OnDisable 호출 주기에 맞춰 항상 중복 없이 등록·해제되도록 구성해야 합니다.

```csharp
         private void OnEnable()
         {
             OnAnyEnemyDied += HandleAllyDied;
         }
```

#### UNITY-001 · 파괴된 Unity 객체에 null 조건 연산자를 사용한다
- 위치: `EnemySeed.cs:24` · 분류: Unity 안티패턴 · Jev 0.64
- 이유: `UnityEngine.Object`의 파괴된 객체는 C#의 `?.`가 검사하는 실제 null과 다릅니다. `target`이 파괴된 뒤에도 `target?.position`이 접근되어 `MissingReferenceException`이 발생할 수 있습니다.
- 수정 제안: Vector3 goal = target != null ? target.position : transform.position;

단, 파괴된 Unity 객체까지 안전하게 처리하려면 참조 생명주기를 관리하거나 `target`을 재할당해야 합니다.

```csharp
Vector3 goal = target?.position ?? transform.position;
```

#### BUG-002 · foreach 중 nearbyAllies.Remove 호출로 InvalidOperationException 발생
- 위치: `EnemySeed.cs:30-35` · 분류: 버그 (+Unity 안티패턴) · Jev 0.82
- 이유: foreach로 nearbyAllies를 순회하는 동안 같은 리스트에서 Remove를 호출합니다. 사망한 적이 목록에 포함된 일반적인 상황에서 열거자가 무효화되어 InvalidOperationException이 발생하고 이벤트 처리와 게임 흐름이 중단됩니다.
- 수정 제안: foreach 대신 `nearbyAllies.RemoveAll(ally => ally == dead);`를 사용하거나, 제거할 항목을 별도로 수집한 뒤 순회가 끝난 후 제거하세요.

```csharp
             foreach (EnemySeed ally in nearbyAllies)
             {
                 if (ally == dead)
                 {
                     nearbyAllies.Remove(ally);
                 }
```

#### BUG-003 · GameManagerSeed 싱글턴 중복 생성 시 Instance를 덮어씀
- 위치: `GameManagerSeed.cs:14-17` · 분류: 버그 (+Unity 안티패턴) · Jev 0.83
- 이유: DontDestroyOnLoad로 기존 GameManagerSeed가 유지된 상태에서 새 씬의 인스턴스가 Awake를 실행하면, 기존 인스턴스를 제거하지 않고 Instance만 새 객체로 덮어씁니다. 그 결과 여러 매니저가 동시에 존재하고, 씬 전환이나 호출 순서에 따라 서로 다른 인스턴스가 사용될 수 있습니다.
- 수정 제안: Awake에서 이미 다른 Instance가 있으면 새 객체를 즉시 제거하고, 유일한 인스턴스일 때만 Instance를 설정하고 DontDestroyOnLoad를 호출합니다. 제거된 객체에서는 이후 초기화가 실행되지 않도록 return해야 합니다.

```csharp
private void Awake()
{
    Instance = this;
    DontDestroyOnLoad(gameObject);
```

#### UNITY-002 · GameManagerSeed의 부모가 있는 오브젝트에 DontDestroyOnLoad 호출
- 위치: `GameManagerSeed.cs:16-17` · 분류: Unity 안티패턴 · Jev 0.72
- 이유: GameManagerSeed가 씬 계층의 Managers 부모 아래에 있으면, 해당 오브젝트에 DontDestroyOnLoad(gameObject)를 호출해도 Unity가 루트 오브젝트가 아니라는 경고를 출력하고 씬 전환 시 보존하지 않을 수 있습니다. 그 결과 매니저가 씬 전환과 함께 파괴됩니다.
- 수정 제안: GameManagerSeed를 루트 오브젝트로 이동한 뒤 DontDestroyOnLoad(gameObject)를 호출하거나, 부모인 Managers 오브젝트 전체를 루트 단위로 보존합니다.

```csharp
Instance = this;
DontDestroyOnLoad(gameObject);
```

#### BUG-004 · WeaponSeed.Fire의 usesLeft 선감소로 인한 배열 범위 초과
- 위치: `WeaponSeed.cs:17-21` · 분류: 버그 (+Unity 안티패턴) · Jev 0.82
- 이유: 사용 가능 횟수가 0인 상태에서 Fire()가 호출되면 usesLeft를 먼저 -1로 감소시킨 뒤 projectilePrefabs[-1]에 접근하므로 IndexOutOfRangeException이 발생합니다. 두 지적은 동일한 원인과 증상을 다룹니다.
- 수정 제안: Fire() 시작 시 CanFire를 확인하고, 발사 가능한 경우에만 usesLeft를 감소시키고 배열에 접근하세요. 예: `if (!CanFire) return; GameObject prefab = projectilePrefabs[--usesLeft];`

```csharp
         public void Fire()
         {
             usesLeft--;
             GameObject prefab = projectilePrefabs[usesLeft];
             Instantiate(prefab, transform.position, transform.rotation);
```


### P2 성능·잠재 버그 — 6건

#### UNITY-003 · Update에서 FindObjectOfType을 매 프레임 호출
- 위치: `HudSeed.cs:12` · 분류: Unity 안티패턴 (+버그, 성능) · Jev 0.92
- 이유: HUD가 갱신될 때마다 씬 전체에서 PlayerHealthSeed를 검색하므로 매 프레임 불필요한 탐색 비용이 발생합니다.
- 수정 제안: PlayerHealthSeed를 SerializeField로 주입하거나 초기화 시 한 번만 FindObjectOfType으로 찾아 참조를 캐시하세요. 가능하면 체력 변경 이벤트를 구독해 변경 시점에만 HUD를 갱신하세요.

```csharp
PlayerHealthSeed health = FindObjectOfType<PlayerHealthSeed>();
```

#### PERF-001 · HP UI를 매 프레임 폴링하고 갱신
- 위치: `HudSeed.cs:13` · 분류: 성능 · Jev 0.83
- 이유: HP가 변하지 않은 프레임에도 라벨의 텍스트를 매번 다시 설정해 불필요한 UI 갱신 비용이 발생합니다.
- 수정 제안: PlayerHealthSeed의 체력 변경 이벤트를 구독하고, HP가 실제로 변경된 경우에만 hpLabel.text를 갱신하세요.

```csharp
hpLabel.text = $"HP {health.Current} / {health.Max}";
```

#### PERF-002 · 문자열 보간으로 매 프레임 HP 문자열 생성
- 위치: `HudSeed.cs:13` · 분류: 성능 · Jev 0.76
- 이유: 매 프레임 문자열 보간을 수행해 새로운 문자열이 생성되므로 불필요한 GC 할당과 수집 부담이 발생합니다.
- 수정 제안: HP 변경 시점에만 문자열을 생성하도록 갱신 로직을 이벤트 기반으로 변경하세요. 단순히 string.Format으로 바꾸기보다 매 프레임 문자열 생성 자체를 제거하는 것이 적절합니다.

```csharp
hpLabel.text = $"HP {health.Current} / {health.Max}";
```

#### UNITY-004 · Update에서 Rigidbody2D.MovePosition 호출 및 이동량의 프레임 의존
- 위치: `PlayerSeed.cs:12-17` · 분류: Unity 안티패턴 · Jev 0.93
- 이유: 물리 오브젝트 이동을 Update에서 수행하고 이동량에 시간 간격을 곱하지 않아 프레임 수에 따라 이동 속도가 달라질 수 있습니다. Rigidbody2D 물리 처리는 FixedUpdate에서 수행하고 fixedDeltaTime을 적용해야 합니다.
- 수정 제안: 입력 값은 Update에서 읽되 Rigidbody2D 참조는 캐싱하고, MovePosition은 FixedUpdate에서 `body.MovePosition(body.position + input * moveSpeed * Time.fixedDeltaTime)`처럼 호출합니다.

```csharp
private void Update()
{
    input = new Vector2(Input.GetAxisRaw("Horizontal"), Input.GetAxisRaw("Vertical"));

    Rigidbody2D body = GetComponent<Rigidbody2D>();
    body.MovePosition(body.position + input * moveSpeed);
```

#### PERF-003 · Update의 GetComponent<Rigidbody2D> 매 프레임 호출
- 위치: `PlayerSeed.cs:16` · 분류: 성능 (+버그, Unity 안티패턴) · Jev 0.79
- 이유: Update에서 같은 오브젝트의 Rigidbody2D를 매 프레임 GetComponent로 검색해 불필요한 반복 비용이 발생합니다. 해당 참조는 런타임 동안 변하지 않으므로 초기화 시 한 번 얻어 재사용해야 합니다.
- 수정 제안: Rigidbody2D 필드를 선언하고 Awake 또는 Start에서 GetComponent<Rigidbody2D>() 결과를 캐싱한 뒤, Update와 FixedUpdate에서는 캐시된 참조를 사용합니다. 인스펙터 할당 방식을 사용할 경우 필수 참조 누락도 함께 검증합니다.

```csharp
Rigidbody2D body = GetComponent<Rigidbody2D>();
```

#### PERF-004 · Animator 문자열 파라미터를 매 프레임 사용
- 위치: `PlayerSeed.cs:20` · 분류: 성능 · Jev 0.65
- 이유: 매 프레임 문자열 이름을 사용해 Animator 파라미터를 설정한다. 해시를 캐싱하면 반복적인 문자열 조회 비용을 줄일 수 있다.
- 수정 제안: ```csharp
private static readonly int IsFireHash = Animator.StringToHash("IsFire");
```
```csharp
animator.SetBool(IsFireHash, firing);
```

```csharp
animator.SetBool("IsFire", firing);
```


### P3 유지보수 — 2건

#### UNITY-005 · 태그 비교에 gameObject.tag를 사용한다
- 위치: `HudSeed.cs:18` · 분류: Unity 안티패턴 · Jev 0.60
- 이유: 태그 비교는 `CompareTag`를 사용해야 하며, Unity의 태그 검사 최적화와 태그 오타 검사를 활용할 수 있습니다.
- 수정 제안: if (other.CompareTag("Player"))

```csharp
if (other.gameObject.tag == "Player")
```

#### UNITY-006 · 체력 값을 public 필드로 노출한다
- 위치: `HudSeed.cs:25-29` · 분류: Unity 안티패턴 · Jev 0.58
- 이유: 외부 코드나 인스펙터에서 체력 값을 임의로 변경할 수 있어 상태 캡슐화가 되지 않습니다. Unity 직렬화가 필요하다면 private 필드와 프로퍼티를 분리하는 편이 안전합니다.
- 수정 제안: [SerializeField] private int current = 10;
[SerializeField] private int max = 10;

public int Current => current;
public int Max => max;

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
| `EnemySeed.cs` | 54 | 0 | 3 | 0 | 0 |
| `GameManagerSeed.cs` | 29 | 0 | 2 | 0 | 0 |
| `HudSeed.cs` | 30 | 0 | 0 | 3 | 2 |
| `PlayerSeed.cs` | 23 | 0 | 0 | 3 | 0 |
| `WeaponSeed.cs` | 36 | 0 | 1 | 0 | 0 |

지적 없는 파일: 0개

## 5. 부록: 검증에서 기각된 지적

없음
