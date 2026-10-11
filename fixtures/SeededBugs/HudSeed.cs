using UnityEngine;
using UnityEngine.UI;

namespace SeededBugs
{
    public class HudSeed : MonoBehaviour
    {
        [SerializeField] private Text hpLabel;

        private void Update()
        {
            PlayerHealthSeed health = FindObjectOfType<PlayerHealthSeed>();
            hpLabel.text = $"HP {health.Current} / {health.Max}";
        }

        private void OnTriggerEnter2D(Collider2D other)
        {
            if (other.gameObject.tag == "Player")
            {
                hpLabel.color = Color.red;
            }
        }
    }

    public class PlayerHealthSeed : MonoBehaviour
    {
        public int Current = 10;
        public int Max = 10;
    }
}
