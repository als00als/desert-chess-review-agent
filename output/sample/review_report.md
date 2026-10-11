# Unity 코드 리뷰 리포트

## 1. 요약

| 항목 | 값 |
| --- | --- |
| 리뷰 파일 | 5개 (172줄, 배치 1개) |
| 리뷰어 | 버그, 성능, Unity 안티패턴 |
| 리뷰어 지적 → 최종 | 19건 → **13건** (검증 기각 0, 병합 6) |
| 등급별 | P0 1 · P1 6 · P2 5 · P3 1 |
| 분류별 | 버그 3 · 성능 4 · Unity 6 |
| 소요 시간 · 토큰 | 64.7초 · 56,682 토큰 (gpt-5.6-luna) |

## 2. 총평

가장 시급한 문제는 `EnemySeed`의 `foreach` 중 컬렉션을 수정해 예외가 발생하는 P0 버그로, 게임 진행을 즉시 중단시킬 수 있으므로 최우선 수정이 필요하다. 그다음으로 정적 이벤트 구독 해제 누락, Unity 객체의 잘못된 null 처리, 싱글턴 중복 생성 및 자식 오브젝트의 `DontDestroyOnLoad` 사용처럼 객체 생명주기와 씬 전환에 관련된 문제를 우선 정리해야 한다. 이후 물리 이동을 `Update`에서 처리하는 문제와 음수 배열 인덱스 접근을 수정해 런타임 동작의 안정성을 확보해야 한다. 마지막으로 매 프레임 반복되는 검색·컴포넌트 조회·문자열 갱신과 공개 상태 필드를 개선해 성능과 캡슐화를 보완하는 순서가 적절하다.

## 3. 지적 목록

### P0 즉시 수정 (크래시·진행 불가) — 1건

#### BUG-001 · foreach 중 nearbyAllies.Remove로 InvalidOperationException 발생
- 위치: `EnemySeed.cs:30-35` · 분류: 버그 (+Unity 안티패턴) · Jev 0.88
- 이유: foreach로 순회 중인 List에서 요소를 제거하면 열거자가 무효화됩니다. 사망한 아군을 제거하는 정상 흐름에서 nearbyAllies.Remove(ally)가 실행되는 즉시 InvalidOperationException이 발생합니다.
- 수정 제안: 순회 없이 `nearbyAllies.Remove(dead);`를 호출하세요. 중복 제거가 필요하다면 반환값을 확인하거나, 여러 조건에 맞는 항목을 제거해야 할 경우 역방향 for문 또는 `RemoveAll`을 사용하세요.

```csharp
foreach (EnemySeed ally in nearbyAllies)
{
    if (ally == dead)
    {
        nearbyAllies.Remove(ally);
    }
}
```


### P1 잘못된 동작 — 6건

#### BUG-002 · EnemySeed의 정적 이벤트 구독 해제 누락
- 위치: `EnemySeed.cs:17-20` · 분류: 버그 (+Unity 안티패턴) · Jev 0.88
- 이유: OnEnable에서 정적 이벤트 OnAnyEnemyDied에 HandleAllyDied를 등록하지만 OnDisable 또는 OnDestroy에서 해제하지 않습니다. 이로 인해 EnemySeed가 파괴된 뒤에도 이벤트가 해당 인스턴스를 참조해 핸들러를 호출하고, 비활성화·재활성화를 반복하면 동일 핸들러가 중복 등록될 수 있습니다.
- 수정 제안: OnDisable에서 동일한 핸들러를 반드시 해제하세요: `private void OnDisable() { OnAnyEnemyDied -= HandleAllyDied; }`

```csharp
private void OnEnable()
{
    OnAnyEnemyDied += HandleAllyDied;
}
```

#### UNITY-001 · Unity 객체에 null 조건 연산자를 사용해 파괴된 참조를 제대로 처리하지 못함
- 위치: `EnemySeed.cs:24` · 분류: Unity 안티패턴 · Jev 0.75
- 이유: `Transform`이 `Destroy`된 경우 C#의 `?.`는 Unity의 가짜 null 판정을 사용하지 않는다. 따라서 파괴된 `target`의 `position` 접근으로 `MissingReferenceException`이 발생할 수 있다.
- 수정 제안: Vector3 goal = target != null ? target.position : transform.position;

```csharp
Vector3 goal = target?.position ?? transform.position;
```

#### UNITY-002 · GameManagerSeed의 자식 오브젝트에 DontDestroyOnLoad 호출
- 위치: `GameManagerSeed.cs:5-17` · 분류: Unity 안티패턴 · Jev 0.38
- 이유: GameManagerSeed가 Managers 부모 오브젝트의 자식이므로 루트 오브젝트가 아니다. Unity에서 DontDestroyOnLoad는 루트 오브젝트에만 적용되므로 경고와 함께 무시되고, 씬 전환 시 GameManagerSeed가 파괴된다.
- 수정 제안: GameManagerSeed를 루트로 분리한 뒤 DontDestroyOnLoad를 호출하거나, Awake에서 transform.SetParent(null)로 루트로 만든 다음 DontDestroyOnLoad(gameObject)를 호출한다. 부모인 Managers 전체를 유지해야 한다면 Managers 루트에 DontDestroyOnLoad를 적용한다.

```csharp
// 씬 계층: =====Managers===== (빈 부모 오브젝트) / GameManagerSeed
...
Instance = this;
DontDestroyOnLoad(gameObject);
```

#### UNITY-003 · GameManagerSeed 싱글턴 중복 생성 및 Instance 덮어쓰기
- 위치: `GameManagerSeed.cs:14-18` · 분류: Unity 안티패턴 · Jev 0.85
- 이유: 기존 인스턴스가 존재해도 새 GameManagerSeed를 삭제하지 않아 씬 재진입이나 중복 배치 시 여러 매니저가 남고, 새 인스턴스가 Instance를 덮어쓴다. 이 과정에서 currentRound 같은 상태가 재초기화될 수 있다.
- 수정 제안: Awake에서 Instance가 이미 존재하고 현재 객체와 다르면 Destroy(gameObject) 후 즉시 return한다. 유효한 단일 인스턴스에만 Instance를 할당하고 초기화 및 DontDestroyOnLoad를 수행한다.

```csharp
private void Awake()
{
    Instance = this;
    DontDestroyOnLoad(gameObject);
    currentRound = startRound;
}
```

#### UNITY-004 · Rigidbody2D MovePosition을 Update에서 프레임 시간 없이 호출
- 위치: `PlayerSeed.cs:16-17` · 분류: Unity 안티패턴 (+버그) · Jev 0.94
- 이유: Rigidbody2D 이동을 Update에서 수행하고 이동량에 Time.fixedDeltaTime을 곱하지 않아 물리 프레임과 동기화되지 않으며, 프레임레이트에 따라 실제 이동 속도가 달라집니다.
- 수정 제안: 입력 수집은 Update에서 유지하고, Rigidbody2D를 Awake에서 캐싱한 뒤 이동은 FixedUpdate에서 `body.MovePosition(body.position + input * moveSpeed * Time.fixedDeltaTime)`로 수행하세요.

```csharp
Rigidbody2D body = GetComponent<Rigidbody2D>();
body.MovePosition(body.position + input * moveSpeed);
```

#### BUG-003 · Fire의 음수 배열 인덱스 접근
- 위치: `WeaponSeed.cs:17-21` · 분류: 버그 (+Unity 안티패턴) · Jev 0.83
- 이유: usesLeft가 0일 때 Fire()가 호출되면 값을 먼저 감소시켜 -1로 만든 뒤 projectilePrefabs[-1]에 접근하므로 IndexOutOfRangeException이 발생합니다. 호출자가 CanFire를 확인하더라도 Fire 자체가 방어하지 않아 잘못된 호출에 취약합니다.
- 수정 제안: Fire() 시작 시 usesLeft가 0 이하인지 검사해 즉시 반환하고, 유효한 경우에만 usesLeft를 감소시켜 배열에 접근하세요. 예: `if (usesLeft <= 0) return; GameObject prefab = projectilePrefabs[--usesLeft];`

```csharp
public void Fire()
{
    usesLeft--;
    GameObject prefab = projectilePrefabs[usesLeft];
    Instantiate(prefab, transform.position, transform.rotation);
}
```


### P2 성능·잠재 버그 — 5건

#### PERF-001 · Update에서 FindObjectOfType로 PlayerHealthSeed를 매 프레임 검색
- 위치: `HudSeed.cs:10-13` · 분류: 성능 (+버그, Unity 안티패턴) · Jev 0.93
- 이유: HudSeed.Update()가 매 프레임 FindObjectOfType<PlayerHealthSeed>()를 호출해 씬 전체를 반복 검색합니다. 체력 값이 변하지 않는 프레임에도 검색 비용이 발생하므로 불필요한 성능 저하가 생깁니다.
- 수정 제안: PlayerHealthSeed를 [SerializeField] 참조로 주입하거나 Awake/Start에서 한 번만 찾아 캐시하세요. 이후에는 PlayerHealthSeed의 체력 변경 이벤트를 구독해 값이 변경될 때만 HUD를 갱신하는 방식이 가장 좋습니다.

```csharp
private void Update()
{
    PlayerHealthSeed health = FindObjectOfType<PlayerHealthSeed>();
    hpLabel.text = $"HP {health.Current} / {health.Max}";
}
```

#### PERF-002 · Update에서 HP 문자열과 hpLabel.text를 매 프레임 갱신
- 위치: `HudSeed.cs:10-14` · 분류: 성능 · Jev 0.71
- 이유: 현재 코드는 HP 값이 바뀌지 않아도 문자열 보간으로 새 문자열을 만들고 hpLabel.text를 계속 대입합니다. 이로 인해 불필요한 GC 할당과 UI 갱신 비용이 발생할 수 있습니다.
- 수정 제안: 현재 체력과 최대 체력의 이전 값을 저장하고 값이 변경된 경우에만 문자열을 생성해 hpLabel.text를 갱신하세요. 가능하면 체력 변경 이벤트에서만 갱신하도록 구성하세요.

```csharp
private void Update()
{
    PlayerHealthSeed health = FindObjectOfType<PlayerHealthSeed>();
    hpLabel.text = $"HP {health.Current} / {health.Max}";
}
```

#### UNITY-005 · 태그 비교에 gameObject.tag를 사용함
- 위치: `HudSeed.cs:18` · 분류: Unity 안티패턴 · Jev 0.53
- 이유: `tag` 프로퍼티를 읽어 문자열 비교를 하는 대신 `CompareTag`를 사용해야 한다. 현재 코드는 태그 비교 시 불필요한 문자열 처리 비용이 발생한다.
- 수정 제안: if (other.CompareTag("Player"))

```csharp
if (other.gameObject.tag == "Player")
```

#### PERF-003 · Update의 GetComponent<Rigidbody2D> 매 프레임 호출
- 위치: `PlayerSeed.cs:12-17` · 분류: 성능 · Jev 0.71
- 이유: 매 프레임 동일한 Rigidbody2D를 컴포넌트 검색으로 가져와 불필요한 실행 비용이 발생합니다.
- 수정 제안: `private Rigidbody2D body;`를 선언하고 Awake에서 `body = GetComponent<Rigidbody2D>();`로 한 번만 가져오세요.

```csharp
private void Update()
{
    input = new Vector2(Input.GetAxisRaw("Horizontal"), Input.GetAxisRaw("Vertical"));

    Rigidbody2D body = GetComponent<Rigidbody2D>();
    body.MovePosition(body.position + input * moveSpeed);
```

#### PERF-004 · Animator 파라미터 문자열을 매 프레임 사용함
- 위치: `PlayerSeed.cs:19-20` · 분류: 성능 · Jev 0.65
- 이유: SetBool(string, bool) 호출 때마다 문자열 이름을 Animator 파라미터 ID로 변환하는 비용이 발생한다.
- 수정 제안: 파라미터 해시를 한 번만 생성해 사용한다.

private static readonly int IsFireHash = Animator.StringToHash("IsFire");

// Update
animator.SetBool(IsFireHash, firing);

```csharp
bool firing = Input.GetMouseButton(0);
animator.SetBool("IsFire", firing);
```


### P3 유지보수 — 1건

#### UNITY-006 · MonoBehaviour의 상태 필드를 public으로 노출함
- 위치: `HudSeed.cs:25-28` · 분류: Unity 안티패턴 · Jev 0.73
- 이유: 외부 코드와 인스펙터에서 체력 값을 임의로 변경할 수 있어 상태 불변식이 깨지기 쉽다. Unity 직렬화가 필요하다면 private 필드와 프로퍼티를 분리하는 편이 안전하다.
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
| `EnemySeed.cs` | 54 | 1 | 2 | 0 | 0 |
| `GameManagerSeed.cs` | 29 | 0 | 2 | 0 | 0 |
| `HudSeed.cs` | 30 | 0 | 0 | 3 | 1 |
| `PlayerSeed.cs` | 23 | 0 | 1 | 2 | 0 |
| `WeaponSeed.cs` | 36 | 0 | 1 | 0 | 0 |

지적 없는 파일: 0개

## 5. 부록: 검증에서 기각된 지적

없음
