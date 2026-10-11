using UnityEngine;

namespace SeededBugs
{
    // 씬 계층: =====Managers===== (빈 부모 오브젝트) / GameManagerSeed
    public class GameManagerSeed : MonoBehaviour
    {
        public static GameManagerSeed Instance;

        [SerializeField] private int startRound = 1;

        private int currentRound;

        private void Awake()
        {
            Instance = this;
            DontDestroyOnLoad(gameObject);
            currentRound = startRound;
        }

        public void NextRound()
        {
            currentRound++;
            Debug.Log("Round " + currentRound);
        }

        public int CurrentRound => currentRound;
    }
}
